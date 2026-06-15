"""
GitHub Issue(candidate-selection 라벨)의 본문에서 JSON을 추출해
data/selections.json을 생성한다.

Issue 본문은 다음과 같은 형태를 기대한다 (이슈 템플릿의 textarea):

### 선택 결과 (JSON)

```json
{
  "date": "20260615",
  "selections": [
    {"prompt_id": "auto_korean_food_001", "filename": "img_20260615_auto_korean_food_001_cand_02.png"},
    ...
  ]
}
```

candidates.json과 대조하여 선택된 항목의 메타(tag, prompt_text, platform_form)를
함께 채워서 selections.json에 저장한다.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_json, save_json, get_logger

ISSUE_BODY = os.environ.get("ISSUE_BODY", "")


def extract_json_block(text: str) -> dict:
    # ```json ... ``` 코드블록을 우선 탐색
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1).strip())
    # 코드블록이 없으면 본문 전체에서 첫 { ... } 블록을 시도
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("이슈 본문에서 JSON을 찾을 수 없습니다")


def main():
    logger = get_logger()

    if not ISSUE_BODY.strip():
        logger.error("ISSUE_BODY가 비어있습니다")
        logger.finalize("failed", {"stage": "parse_selection_issue", "error": "empty issue body"})
        sys.exit(1)

    try:
        payload = extract_json_block(ISSUE_BODY)
    except Exception as e:
        logger.error(f"JSON 파싱 실패: {e}")
        logger.finalize("failed", {"stage": "parse_selection_issue", "error": str(e)})
        sys.exit(1)

    raw_selections = payload.get("selections", [])
    if not raw_selections:
        logger.warn("선택 항목이 없습니다 (전부 스킵된 것으로 처리)")

    candidates = load_json(DATA_DIR / "candidates.json", default={"groups": []})
    groups_by_prompt = {g["prompt_id"]: g for g in candidates.get("groups", [])}

    enriched = []
    for sel in raw_selections:
        prompt_id = sel.get("prompt_id")
        filename = sel.get("filename")
        if not prompt_id or not filename:
            logger.warn(f"잘못된 선택 항목 스킵: {sel}")
            continue

        group = groups_by_prompt.get(prompt_id)
        if not group:
            logger.warn(f"[{prompt_id}] candidates.json에 없는 prompt_id - 스킵")
            continue

        valid_filenames = {img["filename"] for img in group.get("images", [])}
        if filename not in valid_filenames:
            logger.warn(f"[{prompt_id}] {filename}이 후보 목록에 없음 - 스킵")
            continue

        enriched.append({
            "prompt_id": prompt_id,
            "filename": filename,
            "tag": group.get("tag"),
            "prompt_text": group.get("prompt_text", ""),
            "platform_form": group.get("platform_form", "jpg_or_png"),
        })

    save_json(DATA_DIR / "selections.json", {
        "date": payload.get("date", candidates.get("date")),
        "selections": enriched,
    })

    logger.info(f"selections.json 작성 완료: {len(enriched)}개 선택")
    logger.finalize("success", {"stage": "parse_selection_issue", "selected": len(enriched)})


if __name__ == "__main__":
    main()
