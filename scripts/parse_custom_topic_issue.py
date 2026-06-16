"""
GitHub Issue(custom-topic-request 라벨)의 본문에서 JSON을 추출해
data/today_prompts.json에 항목 1개를 추가한다.

01_generate_prompts.py 전체를 재실행하지 않고, 기존 today_prompts.json에
append만 하므로 이미 Colab에서 처리 중인 다른 프롬프트들에 영향을 주지 않는다.

Issue 본문 기대 형식:

```json
{
  "topic": "사이버펑크 스타일의 미래 도시 가로등",
  "tag": "fantasy"
}
```
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_json, save_json, get_logger
from importlib import import_module

_p01 = import_module("01_generate_prompts")
configure_gemini = _p01.configure_gemini
refine_batch_with_gemini = _p01.refine_batch_with_gemini

ISSUE_BODY = os.environ.get("ISSUE_BODY", "")


def extract_json_block(text: str) -> dict:
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("이슈 본문에서 JSON을 찾을 수 없습니다")


def main():
    logger = get_logger()

    if not ISSUE_BODY.strip():
        logger.error("ISSUE_BODY가 비어있습니다")
        logger.finalize("failed", {"stage": "parse_custom_topic_issue", "error": "empty issue body"})
        sys.exit(1)

    try:
        payload = extract_json_block(ISSUE_BODY)
    except Exception as e:
        logger.error(f"JSON 파싱 실패: {e}")
        logger.finalize("failed", {"stage": "parse_custom_topic_issue", "error": str(e)})
        sys.exit(1)

    topic = (payload.get("topic") or "").strip()
    tag = (payload.get("tag") or "other").strip() or "other"

    if not topic:
        logger.error("topic이 비어있습니다")
        logger.finalize("failed", {"stage": "parse_custom_topic_issue", "error": "empty topic"})
        sys.exit(1)

    model = configure_gemini()
    refined_list = refine_batch_with_gemini(
        model,
        [{"skeleton": topic, "category": tag}],
        logger=logger,
    )
    refined_text = refined_list[0] if refined_list else topic

    today = load_json(DATA_DIR / "today_prompts.json", default={"prompts": []})
    prompts = today.get("prompts", [])

    # custom_topic_NNN 형태의 고유 ID 생성
    existing_ids = {p.get("prompt_id", "") for p in prompts}
    idx = 1
    while f"custom_topic_{idx:03d}" in existing_ids:
        idx += 1
    prompt_id = f"custom_topic_{idx:03d}"

    prompts.append({
        "prompt_id": prompt_id,
        "text": refined_text,
        "tag": tag,
        "source": "custom_topic_dashboard",
        "platform_form": "jpg_or_png",
    })

    save_json(DATA_DIR / "today_prompts.json", {"prompts": prompts})

    logger.info(f"즉석 주제 추가됨: {prompt_id} ({topic[:40]})")
    logger.finalize("success", {"stage": "parse_custom_topic_issue", "prompt_id": prompt_id})


if __name__ == "__main__":
    main()
