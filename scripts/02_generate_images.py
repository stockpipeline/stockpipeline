"""
2단계: 이미지 생성 모듈

흐름 (프롬프트 1개당):
  1. Imagen 4 (Generate → Fast → Ultra) 순으로 생성 시도
     (Gemini API 무료 티어, 모델당 RPD 25, 합산 75/일)
  2. 기술적 품질 필터 (밝기/흐림/색상 다양성)
  3. Gemini Vision으로 AI 오류 체크
  4. pHash 중복 체크
  5. 품질/중복 실패 시 변형 폭을 늘려 재생성 (최대 3회)
  6. 3회 모두 실패하면 해당 프롬프트는 건너뜀 (반려 카운트는 올리지 않음 - 이건 업로드 전 단계)

성공한 이미지는 RAW_DIR에 저장되고 manifest.json에 메타가 기록된다.
"""

import base64
import io
import os
import sys
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    DATA_DIR, RAW_DIR, load_config, load_json, save_json,
    get_logger, prepare_work_dirs, make_filename, today_str,
    gemini_generate_with_retry
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

PHASH_DB_PATH = DATA_DIR / "phash_db.json"
PERF_PATH = DATA_DIR / "prompt_performance.json"


# ── Imagen 4 이미지 생성 (Gemini API) ────────────────────
class ImageGenFatalError(Exception):
    """재시도해도 해결되지 않는 오류 (인증실패/권한오류 등). 파이프라인 전체를 멈춰야 함."""
    pass


# 재시도해도 의미 없는 상태 코드: 400(요청오류), 401/403(인증/권한)
FATAL_STATUS_CODES = {400, 401, 403}

IMAGEN_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# 무료 티어 RPD: 각 모델 25/일, 총 75/일.
# 1차→2차→3차 순서로 폴백하며, 각 모델의 일일 한도를 넘으면 429가 발생해
# 다음 모델로 넘어간다.
IMAGEN_MODELS = [
    ("imagen-4.0-generate-001", "imagen4"),
    ("imagen-4.0-fast-generate-001", "imagen4_fast"),
    ("imagen-4.0-ultra-generate-001", "imagen4_ultra"),
]


def call_imagen(model: str, prompt: str, size: str, logger):
    """
    반환: image_bytes (성공) 또는 None (해당 모델 사용 불가/일시적 실패)
    ImageGenFatalError를 raise하면 모든 모델에서 동일하게 실패할
    근본적 문제(인증 등)로, 파이프라인 전체를 멈춰야 함.
    """
    w, h = (int(x) for x in size.split("x"))
    aspect_ratio = "1:1" if w == h else ("4:3" if w > h else "3:4")

    url = f"{IMAGEN_BASE_URL}/{model}:predict"
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "instances": [{"prompt": prompt[:1800]}],  # 480 토큰 제한 대비 여유
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
        },
    }

    for attempt in range(2):
        try:
            logger.info(f"Imagen 요청 전송 ({model}, 시도 {attempt+1}/2)...")
            res = requests.post(url, headers=headers, json=body, timeout=(15, 180))

            if res.status_code == 200:
                data = res.json()
                predictions = data.get("predictions", [])
                if predictions and "bytesBase64Encoded" in predictions[0]:
                    return base64.b64decode(predictions[0]["bytesBase64Encoded"])
                logger.warn(f"Imagen 응답에 이미지 없음: {str(data)[:200]}")
                return None

            if res.status_code == 429:
                # 해당 모델의 일일/분당 한도 초과 - 다음 모델로 폴백
                logger.warn(f"Imagen {model} 429 (한도 초과) - 다음 모델로 폴백: {res.text[:150]}")
                return None

            if res.status_code in FATAL_STATUS_CODES:
                logger.error(f"Imagen 치명적 오류 {res.status_code}: {res.text[:300]}")
                raise ImageGenFatalError(f"{model} {res.status_code}: {res.text[:300]}")

            logger.warn(f"Imagen 응답 오류 {res.status_code} (시도 {attempt+1}/2): {res.text[:200]}")
            time.sleep(10)
        except ImageGenFatalError:
            raise
        except requests.exceptions.RequestException as e:
            logger.warn(f"Imagen 요청 예외 (시도 {attempt+1}/2): {e}")
            time.sleep(10)

    return None


def generate_image_bytes(prompt: str, config: dict, logger):
    """
    반환: (image_bytes, source_model)
    ImageGenFatalError는 그대로 propagate되어 상위(main)에서
    파이프라인 전체를 즉시 멈추는 신호로 쓰인다.

    Imagen 4 Generate -> Fast -> Ultra 순서로 폴백.
    각 모델은 무료 티어 RPD 25 (합산 75/일).
    """
    img_cfg = config["image"]
    size = img_cfg["size"]

    for model, source_name in IMAGEN_MODELS:
        logger.info(f"Imagen 생성 시도 ({source_name})")
        data = call_imagen(model, prompt, size, logger)
        if data:
            return data, source_name

    return None, None


# ── 기술적 품질 필터 ─────────────────────────────────────
def technical_quality_check(img: Image.Image, config: dict, category: str = None) -> tuple:
    qf = dict(config["quality_filter"])
    overrides = qf.get("category_overrides", {}).get(category, {})
    qf.update(overrides)

    arr = np.array(img.convert("L"), dtype=np.float32)

    brightness = float(arr.mean())
    if brightness < qf["min_brightness"]:
        return False, f"too dark (brightness={brightness:.1f})"
    if brightness > qf["max_brightness"]:
        return False, f"too bright (brightness={brightness:.1f})"

    # 라플라시안 분산으로 흐림 감지
    gy, gx = np.gradient(arr)
    sharpness = float((gx ** 2 + gy ** 2).var())
    if sharpness < qf["min_sharpness"]:
        return False, f"too blurry (sharpness={sharpness:.1f})"

    # 색상 다양성 (RGB 채널별 표준편차)
    rgb = np.array(img.convert("RGB"), dtype=np.float32)
    color_std = float(rgb.std())
    if color_std < qf["min_color_variety"]:
        return False, f"too flat/empty (color_std={color_std:.1f})"

    return True, "ok"


# ── Gemini Vision AI 오류 체크 ──────────────────────────
def gemini_vision_check(img: Image.Image, logger) -> tuple:
    """
    Gemini Vision으로 명백한 AI 생성 오류를 체크한다.
    실패해도 파이프라인을 막지 않도록 예외 시 통과 처리.
    429(rate limit)는 짧게 대기 후 1회 재시도.
    """
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-flash-latest")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    img_bytes = buf.getvalue()

    prompt = (
        "Look at this AI-generated stock image candidate. "
        "Check for obvious AI generation errors: malformed hands/fingers, "
        "distorted faces, broken text, anatomical errors, unnatural "
        "textures or colors for the subject, or a messed-up/incomplete "
        "white background.\n\n"
        "Reply with ONLY one word: PASS if no obvious errors, "
        "or FAIL if there is a clear AI error."
    )

    for attempt in range(2):
        try:
            # 분당 요청 수 제한 완화를 위한 기본 간격
            time.sleep(4)
            resp = gemini_generate_with_retry(
                model,
                [{"role": "user", "parts": [prompt, {"mime_type": "image/png", "data": img_bytes}]}],
                logger=logger,
                max_retries=2,
                base_wait=65,
            )
            text = resp.text.strip().upper()
            if "FAIL" in text:
                return False, "gemini vision flagged AI artifact"
            return True, "ok"
        except Exception as e:
            logger.warn(f"Gemini Vision 체크 실패(통과 처리): {e}")
            return True, "vision check skipped"

    return True, "vision check skipped"


# ── pHash 중복 체크 ──────────────────────────────────────
def compute_phash(img: Image.Image) -> str:
    import imagehash
    return str(imagehash.phash(img))


def is_duplicate(phash: str, db: dict, threshold: float) -> bool:
    import imagehash
    new_hash = imagehash.hex_to_hash(phash)
    max_bits = len(new_hash.hash) ** 2  # 64 for 8x8

    for existing in db.values():
        old_hash = imagehash.hex_to_hash(existing["phash"])
        dist = new_hash - old_hash
        similarity = 1 - (dist / max_bits)
        if similarity >= threshold:
            return True
    return False


# ── 메인 처리: 프롬프트 1개 → 이미지 1장 ──────────────────
def process_one_prompt(prompt_obj: dict, config: dict, phash_db: dict, performance: dict, logger) -> dict:
    prompt_id = prompt_obj["prompt_id"]
    base_prompt = prompt_obj["text"]
    max_retry = config["duplicate_filter"]["max_retry"]
    threshold = config["duplicate_filter"]["phash_threshold"]

    for attempt in range(max_retry):
        # 변형 폭 점점 키우기 (시도마다 약한 텍스트 변형 추가)
        prompt = base_prompt
        if attempt == 1:
            prompt += ", slightly different angle and lighting"
        elif attempt >= 2:
            prompt += ", different composition variation, alternate styling"

        logger.info(f"[{prompt_id}] 생성 시도 {attempt+1}/{max_retry}")
        img_bytes, source = generate_image_bytes(prompt, config, logger)

        if img_bytes is None:
            logger.warn(f"[{prompt_id}] 이미지 생성 실패 (생성 API 문제)")
            continue

        try:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        except Exception as e:
            logger.warn(f"[{prompt_id}] 이미지 디코딩 실패: {e}")
            continue

        # 1차 품질 필터
        ok, reason = technical_quality_check(img, config, prompt_obj.get("tag"))
        if not ok:
            logger.warn(f"[{prompt_id}] 품질 필터 탈락: {reason}")
            continue

        # 2차 Gemini Vision
        ok, reason = gemini_vision_check(img, logger)
        if not ok:
            logger.warn(f"[{prompt_id}] Vision 체크 탈락: {reason}")
            continue

        # 3차 중복 체크
        phash = compute_phash(img)
        if is_duplicate(phash, phash_db, threshold):
            logger.warn(f"[{prompt_id}] 중복 이미지로 폐기")
            # 중복 카운트 업데이트 (다음번 변형 강도 조절용)
            perf = performance.setdefault(prompt_id, {})
            perf["recent_duplicate_count"] = perf.get("recent_duplicate_count", 0) + 1
            continue

        # 통과 → 저장
        filename = make_filename(prompt_id, "orig", 1, "png")
        save_path = RAW_DIR / filename
        img.save(save_path, format="PNG")

        # phash DB 등록
        phash_db[filename] = {
            "phash": phash,
            "prompt_id": prompt_id,
            "date": today_str(),
        }

        # 성공 시 중복 카운트 리셋
        perf = performance.setdefault(prompt_id, {})
        perf["recent_duplicate_count"] = 0

        logger.success(f"[{prompt_id}] 생성 성공 ({source}) → {filename}")
        return {
            "prompt_id": prompt_id,
            "filename": filename,
            "tag": prompt_obj.get("tag", "other"),
            "platform_form": prompt_obj.get("platform_form", "jpg_or_png"),
            "source_model": source,
            "prompt_text": prompt,
        }

    logger.warn(f"[{prompt_id}] {max_retry}회 모두 실패 → 건너뜀")
    return None


# ── 30일 지난 phash 정리 ──────────────────────────────────
def cleanup_old_phashes(phash_db: dict, retention_days: int) -> dict:
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y%m%d")
    return {k: v for k, v in phash_db.items() if v.get("date", "99999999") >= cutoff}


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()
    config = load_config()
    prepare_work_dirs()

    today_prompts = load_json(DATA_DIR / "today_prompts.json", default={"prompts": []})["prompts"]
    phash_db = load_json(PHASH_DB_PATH, default={})
    performance = load_json(PERF_PATH, default={})

    phash_db = cleanup_old_phashes(phash_db, config["storage"]["phash_retention_days"])

    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY가 설정되지 않았습니다")
        logger.finalize("failed", {"stage": "image_generation", "error": "missing GEMINI_API_KEY"})
        sys.exit(1)

    results = []
    fatal_error = None
    for p in today_prompts:
        try:
            r = process_one_prompt(p, config, phash_db, performance, logger)
        except ImageGenFatalError as e:
            logger.error(f"Imagen 치명적 오류로 파이프라인 중단: {e}")
            fatal_error = str(e)
            break
        if r:
            results.append(r)

    save_json(PHASH_DB_PATH, phash_db)
    save_json(PERF_PATH, performance)
    save_json(DATA_DIR / "generated_images.json", {"images": results})

    success_count = len(results)
    total_count = len(today_prompts)
    logger.info(f"이미지 생성 완료: {success_count}/{total_count}")

    if fatal_error:
        logger.finalize("failed", {
            "stage": "image_generation",
            "generated": success_count,
            "attempted": total_count,
            "error": f"Imagen API 인증/요청 오류 - 확인 필요: {fatal_error}",
        })
        sys.exit(1)

    if success_count == 0 and total_count > 0:
        logger.finalize("failed", {
            "stage": "image_generation",
            "generated": 0,
            "attempted": total_count,
            "error": "no images passed all filters",
        })
        sys.exit(1)

    status = "success" if success_count == total_count else "partial"
    logger.finalize(status, {
        "stage": "image_generation",
        "generated": success_count,
        "attempted": total_count,
    })


if __name__ == "__main__":
    main()
