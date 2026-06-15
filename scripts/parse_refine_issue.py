"""
GitHub Issue(refine-request 라벨)의 본문에서 JSON을 추출해
data/refine_requests.json에 항목을 추가한다.

Issue 본문 기대 형식:

```json
{
  "prompt_id": "auto_korean_food_001",
  "prompt_text": "...",
  "tag": "food",
  "seed": 123456789,
  "source_filename": "img_20260615_auto_korean_food_001_cand_02.png",
  "refine_steps": 24
}
```

Colab의 "정밀 재생성" 셀이 이 파일을 읽어서 처리한 뒤,
처리된 요청은 비운다 (Colab이 push).
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_json, save_json, get_logger

ISSUE_BODY = os.environ.get("ISSUE_BODY", "")

DEFAULT_REFINE_STEPS = 24


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
        logger.finalize("failed", {"stage": "parse_refine_issue", "error": "empty issue body"})
        sys.exit(1)

    try:
        payload = extract_json_block(ISSUE_BODY)
    except Exception as e:
        logger.error(f"JSON 파싱 실패: {e}")
        logger.finalize("failed", {"stage": "parse_refine_issue", "error": str(e)})
        sys.exit(1)

    required = ["prompt_text", "seed"]
    missing = [k for k in required if payload.get(k) is None]
    if missing:
        logger.error(f"필수 필드 누락: {missing}")
        logger.finalize("failed", {"stage": "parse_refine_issue", "error": f"missing fields: {missing}"})
        sys.exit(1)

    requests_data = load_json(DATA_DIR / "refine_requests.json", default={"requests": []})

    entry = {
        "prompt_id": payload.get("prompt_id"),
        "prompt_text": payload["prompt_text"],
        "tag": payload.get("tag", "other"),
        "seed": payload["seed"],
        "source_filename": payload.get("source_filename"),
        "refine_steps": payload.get("refine_steps", DEFAULT_REFINE_STEPS),
        "requested_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    requests_data["requests"].append(entry)
    save_json(DATA_DIR / "refine_requests.json", requests_data)

    logger.info(f"정밀 재생성 요청 추가됨: {entry['prompt_id']}")
    logger.finalize("success", {"stage": "parse_refine_issue", "prompt_id": entry["prompt_id"]})


if __name__ == "__main__":
    main()
