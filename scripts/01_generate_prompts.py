"""
1단계: 프롬프트 생성 모듈

- prompts.json (사용자가 관리 페이지에서 추가한 활성 프롬프트)을 기본으로 사용
- 부족하면 prompt_templates.json의 규칙 기반 템플릿으로 채움
- Gemini Flash로 상업적 보정 + 미세 변형 적용
- 변형 강도는 중복 발생 이력에 따라 단계적으로 조절
- 카테고리 가중치(config.json) + 승인율 기반 우선순위 반영
"""

import json
import random
import re
import sys
import time
from pathlib import Path

import google.generativeai as genai

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    DATA_DIR, load_config, load_json, save_json, get_logger,
    gemini_generate_with_retry
)

TEMPLATES_PATH = DATA_DIR / "prompt_templates.json"
PROMPTS_PATH = DATA_DIR / "prompts.json"
PERF_PATH = DATA_DIR / "prompt_performance.json"


def configure_gemini():
    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 없습니다")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-flash-latest")


# ── 규칙 기반 뼈대 생성 ──────────────────────────────────
def build_skeleton(category: str, templates: dict, variation_level: int = 0) -> dict:
    """
    variation_level: 0 (기본), 1 (중간), 2 (강한 변형)
    """
    cat = templates["categories"][category]
    subject = random.choice(cat["subjects"])
    composition = random.choice(cat["compositions"])

    parts = [subject, composition]

    if variation_level == 0:
        parts.append(random.choice(cat["variations_light"]))
    elif variation_level == 1:
        parts.append(random.choice(cat["variations_light"]))
        parts.append(random.choice(cat["variations_detail"]))
    else:
        parts.append(random.choice(cat["variations_strong"]))
        parts.append(random.choice(cat["variations_detail"]))

    quality = templates["quality_keywords"][category]
    skeleton = ", ".join(parts) + ", " + quality

    return {
        "skeleton": skeleton,
        "tag": cat["tag"],
        "platform_form": cat["platform_form"],
    }


# ── Gemini 보정 ────────────────────────────────────────
def refine_with_gemini(model, skeleton: str, category: str, logger=None) -> str:
    system = (
        "You are an expert Adobe Stock / Freepik prompt engineer. "
        "You will receive a draft image generation prompt (a 'skeleton'). "
        "Refine it into a polished, highly commercial English prompt for "
        "an AI image generator (Flux.1 Schnell).\n\n"
        "Rules:\n"
        "- Do NOT change the core subject, background, or category.\n"
        "- You MAY adjust adjectives, lighting words, composition wording, "
        "and minor decorative details.\n"
        "- Keep it isolated on a white background unless the skeleton says otherwise.\n"
        "- Output ONLY the final prompt text, one line, no quotes, no explanation."
    )
    user = f"Category: {category}\nDraft skeleton: {skeleton}\n\nRefine this into the final prompt."

    try:
        time.sleep(4)  # 분당 요청 수 제한 완화
        resp = gemini_generate_with_retry(
            model,
            [{"role": "user", "parts": [system + "\n\n" + user]}],
            logger=logger, max_retries=2, base_wait=65,
        )
        text = resp.text.strip().strip('"')
        # 너무 짧거나 비어있으면 원본 사용
        if len(text) < 20:
            return skeleton
        return text
    except Exception:
        return skeleton


# ── 변형 레벨 결정 ──────────────────────────────────────
def get_variation_level(prompt_id: str, performance: dict) -> int:
    """
    최근 중복 폐기 횟수를 기준으로 변형 강도를 올린다.
    0: 기본, 1: 중간, 2: 강함
    """
    perf = performance.get(prompt_id, {})
    dup_count = perf.get("recent_duplicate_count", 0)
    if dup_count >= 2:
        return 2
    if dup_count >= 1:
        return 1
    return 0


# ── 활성 프롬프트 선택 (성과 기반) ────────────────────────
def select_active_prompts(prompts: list, performance: dict, n: int) -> list:
    """
    활성화된 사용자 프롬프트 중에서 승인율 높은 것을 우선 선택.
    데이터가 없는 신규 프롬프트는 중간 우선순위로 취급.
    """
    active = [p for p in prompts if p.get("active", True)]

    def score(p):
        perf = performance.get(p["id"], {})
        approved = perf.get("approved", 0)
        rejected = perf.get("rejected", 0)
        total = approved + rejected
        if total == 0:
            return 0.5  # 데이터 없으면 중간값
        return approved / total

    active_sorted = sorted(active, key=score, reverse=True)
    return active_sorted[:n]


# ── 카테고리별 목표 개수 계산 ────────────────────────────
def compute_category_quota(weights: dict, total: int) -> dict:
    total_weight = sum(weights.values())
    quota = {}
    remaining = total
    for i, (cat, w) in enumerate(weights.items()):
        if i == len(weights) - 1:
            quota[cat] = remaining
        else:
            n = round(total * w / total_weight)
            quota[cat] = n
            remaining -= n
    return quota


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()
    config = load_config()
    templates = load_json(TEMPLATES_PATH, default={})
    prompts = load_json(PROMPTS_PATH, default={"prompts": []}).get("prompts", [])
    performance = load_json(PERF_PATH, default={})

    daily_count = config["daily_prompt_count"]
    logger.info(f"오늘의 프롬프트 {daily_count}개 생성 시작")

    model = configure_gemini()

    # 1) 사용자 활성 프롬프트 우선 사용
    user_selected = select_active_prompts(prompts, performance, daily_count)
    logger.info(f"사용자 프롬프트 {len(user_selected)}개 선택됨")

    final_prompts = []
    for p in user_selected:
        var_level = get_variation_level(p["id"], performance)
        skeleton = p["text"]
        category = p.get("tag", "other")
        quality_kw = templates.get("quality_keywords", {}).get(category, "")
        if quality_kw and quality_kw not in skeleton:
            skeleton = f"{skeleton}, {quality_kw}"

        refined = refine_with_gemini(model, skeleton, category, logger)
        final_prompts.append({
            "prompt_id": p["id"],
            "text": refined,
            "tag": category,
            "source": "user",
            "platform_form": "jpg_or_png",
        })

    # 2) 부족하면 규칙 기반 템플릿으로 채움
    remaining = daily_count - len(final_prompts)
    if remaining > 0 and templates:
        logger.info(f"템플릿 기반으로 {remaining}개 추가 생성")
        quota = compute_category_quota(config["category_weights"], remaining)

        idx = 0
        for category, n in quota.items():
            if category not in templates.get("categories", {}):
                continue
            for _ in range(n):
                idx += 1
                var_level = random.choice([0, 0, 1])  # 기본 위주, 가끔 중간
                sk = build_skeleton(category, templates, var_level)
                refined = refine_with_gemini(model, sk["skeleton"], category, logger)
                prompt_id = f"auto_{category}_{idx:03d}"
                final_prompts.append({
                    "prompt_id": prompt_id,
                    "text": refined,
                    "tag": sk["tag"],
                    "source": "template",
                    "platform_form": sk["platform_form"],
                })

    logger.info(f"총 {len(final_prompts)}개 프롬프트 준비 완료")

    # 결과 저장 (다음 단계에서 사용)
    save_json(DATA_DIR / "today_prompts.json", {"prompts": final_prompts})

    logger.finalize("success", {
        "stage": "prompt_generation",
        "total_prompts": len(final_prompts),
        "from_user": len(user_selected),
        "from_template": len(final_prompts) - len(user_selected),
    })


if __name__ == "__main__":
    main()
