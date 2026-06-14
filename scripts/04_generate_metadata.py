"""
4단계: 메타데이터 생성

흐름:
  1. 이미지를 Gemini Vision에 보내 5레이어 구조로 태그/제목 생성
     (핵심주제 / 시각묘사 / 상업용도 / 감성분위기 / 기술태그)
  2. 블랙리스트 필터링 (브랜드명, 인물명 등 제거)
  3. 첫 10개 태그를 핵심 주제 우선으로 정렬
  4. 플랫폼별 AI 표기 자동 삽입
     - Adobe: AI_Generated=Yes, 제목에 "AI Generated" 추가
     - Shutterstock: ai_generated=true
     - Freepik: _ai_generated 태그 추가
  5. CSV 3종 출력 (Adobe / Shutterstock / Freepik)
"""

import csv
import io
import os
import sys
import time
from pathlib import Path

import google.generativeai as genai
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    DATA_DIR, UPSCALED_DIR, CUTOUT_DIR,
    load_config, load_json, save_json, get_logger, today_str,
    gemini_generate_with_retry
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

BLACKLIST_PATH = DATA_DIR / "tag_blacklist.json"

DEFAULT_BLACKLIST = [
    "mcdonalds", "starbucks", "nike", "adidas", "samsung", "apple",
    "coca cola", "pepsi", "cj", "ottogi", "nongshim",
    "disney", "marvel", "pokemon", "nintendo",
    "photograph", "photo of real person",
]


def ensure_blacklist():
    if not BLACKLIST_PATH.exists():
        save_json(BLACKLIST_PATH, {"blacklist": DEFAULT_BLACKLIST})
    return load_json(BLACKLIST_PATH, default={"blacklist": DEFAULT_BLACKLIST})["blacklist"]


# ── Gemini로 메타데이터 생성 ─────────────────────────────
def generate_metadata(image_path: Path, prompt_text: str, category: str, model, logger=None) -> dict:
    img = Image.open(image_path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    system = (
        "You are an Adobe Stock / Shutterstock / Freepik metadata expert.\n"
        "Given this stock image, generate metadata optimized for search discovery.\n\n"
        "Build keywords in 5 layers:\n"
        "1. Core subject (most important search terms, romanized Korean names if applicable)\n"
        "2. Visual description (composition, colors, textures)\n"
        "3. Commercial use cases (restaurant menu, food delivery, blog, design asset, etc.)\n"
        "4. Mood/atmosphere (appetizing, fresh, cozy, vibrant, etc.)\n"
        "5. Technical tags (isolated, white background, studio lighting, etc.)\n\n"
        "Order ALL keywords so the first 10 are the most important, highest-search-volume terms "
        "(layer 1 first).\n\n"
        "Rules:\n"
        "- Do NOT include brand names, logos, real people's names, or copyrighted characters.\n"
        "- Generate exactly 49 unique English keywords total.\n"
        "- Generate a commercial title, 50-70 characters, starting with the main subject.\n\n"
        f"Original generation prompt (for context): {prompt_text}\n"
        f"Category: {category}\n\n"
        'Respond ONLY with JSON: {"title": "...", "keywords": ["k1","k2",...49 items]}'
    )

    try:
        time.sleep(4)  # 분당 요청 수 제한 완화
        resp = gemini_generate_with_retry(
            model,
            [{"role": "user", "parts": [system, {"mime_type": "image/jpeg", "data": buf.getvalue()}]}],
            logger=logger, max_retries=2, base_wait=65,
        )
        text = resp.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        import json
        data = json.loads(text.strip())
        return data
    except Exception as e:
        if logger:
            logger.warn(f"메타데이터 생성 실패, 기본값 사용: {e}")
        # 폴백: 최소한의 기본 메타데이터
        return {
            "title": f"{category.replace('_', ' ').title()} - AI Generated Stock Image",
            "keywords": [category, "generative ai", "digital art", "stock image",
                          "commercial use", "high resolution", "design asset",
                          "isolated background", "white background", "modern"],
        }


# ── 블랙리스트 필터 ────────────────────────────────────────
def filter_keywords(keywords: list, blacklist: list) -> list:
    bl_lower = [b.lower() for b in blacklist]
    filtered = []
    for kw in keywords:
        kw_lower = kw.lower().strip()
        if any(b in kw_lower for b in bl_lower):
            continue
        if kw_lower and kw_lower not in [f.lower() for f in filtered]:
            filtered.append(kw.strip())
    return filtered


# ── 플랫폼별 메타데이터 가공 ────────────────────────────────
def build_platform_metadata(title: str, keywords: list, config: dict) -> dict:
    meta_cfg = config["metadata"]

    adobe_keywords = keywords[:meta_cfg["tag_count_adobe"]]
    if "generative ai" not in [k.lower() for k in adobe_keywords]:
        adobe_keywords = adobe_keywords[:-1] + ["generative ai"]
    adobe_title = f"{title} | AI Generated"

    ss_keywords = keywords[:meta_cfg["tag_count_shutterstock"]]
    ss_title = title

    fp_keywords = keywords[:meta_cfg["tag_count_freepik"]]
    if "_ai_generated" not in fp_keywords:
        fp_keywords = fp_keywords[:-1] + ["_ai_generated"]

    return {
        "adobe": {"title": adobe_title, "keywords": adobe_keywords, "ai_generated": "Yes"},
        "shutterstock": {"title": ss_title, "keywords": ss_keywords, "ai_generated": "true"},
        "freepik": {"title": title, "keywords": fp_keywords, "ai_generated": True},
    }


# ── CSV 출력 ────────────────────────────────────────────
def write_csvs(items: list, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Adobe Stock CSV
    with open(out_dir / "adobe_stock.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Filename", "Title", "Keywords", "Category", "Editorial", "Mature Content", "AI Generated"])
        for it in items:
            m = it["metadata"]["adobe"]
            w.writerow([
                it["orig_jpg"], m["title"], ", ".join(m["keywords"]),
                "", "No", "No", m["ai_generated"],
            ])

    # Shutterstock CSV
    with open(out_dir / "shutterstock.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Filename", "Description", "Keywords", "Categories", "Editorial", "Mature Content", "Illustration", "Ai_generated"])
        for it in items:
            m = it["metadata"]["shutterstock"]
            w.writerow([
                it["orig_jpg"], m["title"], ", ".join(m["keywords"]),
                "", "no", "no", "yes", m["ai_generated"],
            ])

    # Freepik CSV
    with open(out_dir / "freepik.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Filename", "Title", "Keywords", "AI_generated"])
        for it in items:
            m = it["metadata"]["freepik"]
            w.writerow([
                it["cutout_png"], m["title"], ", ".join(m["keywords"]), "true",
            ])


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()
    config = load_config()
    blacklist = ensure_blacklist()

    processed = load_json(DATA_DIR / "processed_images.json", default={"images": []})["images"]
    if not processed:
        logger.warn("처리할 이미지가 없습니다")
        logger.finalize("partial", {"stage": "metadata", "processed": 0})
        return

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-flash-latest")

    results = []
    for item in processed:
        jpg_path = UPSCALED_DIR / item["orig_jpg"]
        if not jpg_path.exists():
            logger.warn(f"파일 없음: {item['orig_jpg']}")
            continue

        meta = generate_metadata(jpg_path, item.get("prompt_text", ""), item["tag"], model, logger)
        keywords = filter_keywords(meta.get("keywords", []), blacklist)
        title = meta.get("title", "AI Generated Stock Image")

        platform_meta = build_platform_metadata(title, keywords, config)

        results.append({
            **item,
            "title": title,
            "keywords": keywords,
            "metadata": platform_meta,
        })
        logger.success(f"[{item['orig_jpg']}] 메타데이터 생성 완료 ({len(keywords)} keywords)")

    csv_dir = DATA_DIR / "csv_output" / today_str()
    write_csvs(results, csv_dir)
    logger.info(f"CSV 3종 출력 완료: {csv_dir}")

    save_json(DATA_DIR / "metadata_results.json", {"images": results})

    success = len(results)
    total = len(processed)
    status = "success" if success == total else ("partial" if success > 0 else "failed")

    logger.finalize(status, {
        "stage": "metadata",
        "processed": success,
        "attempted": total,
        "csv_dir": str(csv_dir),
    })

    if status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
