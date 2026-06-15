"""
3단계: 업스케일 + 누끼(배경 제거) + EXIF 정리

입력: data/selections.json (대시보드에서 선택된 후보 이미지 목록)
      원본 파일은 data/candidates_raw/ 에 있음 (Colab이 push한 것)

흐름 (이미지 1장당):
  1. Real-ESRGAN으로 4배 업스케일 (1024 -> 4096, 16MP)
     - realesrgan-ncnn-vulkan 바이너리가 없으면 Pillow 리사이즈로 폴백
  2. 원본(업스케일본)은 JPG로 변환 → Adobe/Shutterstock용
  3. rembg로 배경 제거 → 투명 PNG → Freepik용
  4. 둘 다 EXIF 메타데이터 정리 (AI 생성 흔적 제거)
"""

import io
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    DATA_DIR, RAW_DIR, UPSCALED_DIR, CUTOUT_DIR,
    load_config, load_json, save_json, get_logger, today_str, prepare_work_dirs
)

CANDIDATES_RAW_DIR = DATA_DIR / "candidates_raw"
REALESRGAN_BIN = "realesrgan-ncnn-vulkan"  # PATH에 있으면 사용, 없으면 폴백


# ── 업스케일 ────────────────────────────────────────────
def upscale_image(input_path: Path, output_path: Path, config: dict, logger) -> bool:
    scale = config["upscale"]["scale"]
    model = config["upscale"]["model"]

    # realesrgan 바이너리 시도
    cmd = [
        REALESRGAN_BIN,
        "-i", str(input_path),
        "-o", str(output_path),
        "-n", model,
        "-s", str(scale),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        if proc.returncode == 0 and output_path.exists():
            return True
        logger.warn(f"realesrgan 실행 실패(returncode={proc.returncode}), Pillow 폴백 사용")
    except FileNotFoundError:
        logger.warn("realesrgan-ncnn-vulkan 바이너리 없음, Pillow 폴백 사용")
    except subprocess.TimeoutExpired:
        logger.warn("realesrgan 타임아웃, Pillow 폴백 사용")
    except Exception as e:
        logger.warn(f"realesrgan 오류({e}), Pillow 폴백 사용")

    # Pillow 폴백 (LANCZOS 리샘플)
    try:
        img = Image.open(input_path)
        new_size = (img.width * scale, img.height * scale)
        upscaled = img.resize(new_size, Image.LANCZOS)
        upscaled.save(output_path)
        return True
    except Exception as e:
        logger.error(f"Pillow 업스케일도 실패: {e}")
        return False


# ── EXIF 정리 ────────────────────────────────────────────
def strip_exif(img: Image.Image) -> Image.Image:
    """AI 생성 메타데이터(EXIF/C2PA 등) 제거. 픽셀 데이터만 남긴 새 이미지를 만든다."""
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    return clean


# ── 누끼(배경 제거) ────────────────────────────────────────
def remove_background(img: Image.Image, logger) -> Image.Image:
    try:
        from rembg import remove
        result = remove(img)
        return result
    except BaseException as e:
        # onnxruntime 미설치 등 어떤 예외든 파이프라인을 막지 않도록 처리
        logger.warn(f"rembg 처리 실패({type(e).__name__}: {e}) - 원본을 그대로 사용")
        return img.convert("RGBA")


# ── 메인 처리: 이미지 1장 ───────────────────────────────
def process_one_image(item: dict, config: dict, logger) -> dict:
    """
    item: selections.json의 한 항목
          {"prompt_id":..., "filename":"img_{date}_{prompt_id}_cand_{seq}.png",
           "tag":..., "prompt_text":..., "platform_form":...}
    """
    filename = item["filename"]
    raw_path = CANDIDATES_RAW_DIR / filename
    if not raw_path.exists():
        logger.warn(f"후보 원본 파일 없음: {filename}")
        return None

    # img_{date}_{prompt_id}_cand_{seq}.png -> base_name, seq
    stem = filename.rsplit(".", 1)[0]
    if "_cand_" not in stem:
        logger.warn(f"예상치 못한 파일명 형식: {filename}")
        return None
    base_name, seq = stem.rsplit("_cand_", 1)

    # 1) 업스케일
    upscaled_png = UPSCALED_DIR / f"{base_name}_orig_{seq}.png"
    ok = upscale_image(raw_path, upscaled_png, config, logger)
    if not ok:
        logger.warn(f"[{filename}] 업스케일 실패")
        return None

    # 2) 원본 JPG 생성 (Adobe/Shutterstock용)
    img = Image.open(upscaled_png).convert("RGB")
    img_clean = strip_exif(img)
    jpg_filename = f"{base_name}_orig_{seq}.jpg"
    jpg_path = UPSCALED_DIR / jpg_filename
    img_clean.save(jpg_path, format="JPEG", quality=95, exif=b"")

    # 3) 누끼 PNG 생성 (Freepik용)
    cutout = remove_background(img, logger)
    cutout_clean = strip_exif(cutout)
    png_filename = f"{base_name}_cutout_{seq}.png"
    png_path = CUTOUT_DIR / png_filename
    cutout_clean.save(png_path, format="PNG")

    logger.success(f"[{filename}] 업스케일+누끼 완료")

    return {
        "prompt_id": item["prompt_id"],
        "tag": item["tag"],
        "orig_jpg": jpg_filename,
        "cutout_png": png_filename,
        "prompt_text": item.get("prompt_text", ""),
    }


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()
    config = load_config()
    prepare_work_dirs()

    selections = load_json(DATA_DIR / "selections.json", default={"selections": []})["selections"]

    if not selections:
        logger.warn("처리할 선택 항목이 없습니다 (data/selections.json)")
        logger.finalize("partial", {"stage": "upscale_cutout", "processed": 0})
        return

    results = []
    for item in selections:
        try:
            r = process_one_image(item, config, logger)
        except Exception as e:
            logger.error(f"[{item.get('filename')}] 처리 중 예외: {e}")
            r = None
        if r:
            results.append(r)

    save_json(DATA_DIR / "processed_images.json", {"images": results})

    success = len(results)
    total = len(selections)
    logger.info(f"업스케일/누끼 완료: {success}/{total}")

    status = "success" if success == total else "partial"
    if success == 0:
        status = "failed"

    logger.finalize(status, {
        "stage": "upscale_cutout",
        "processed": success,
        "attempted": total,
    })

    if status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
