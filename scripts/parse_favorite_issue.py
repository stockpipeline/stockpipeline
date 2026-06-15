"""
GitHub Issue(favorite-add 라벨)의 본문에서 JSON을 추출해
data/favorites.json에 항목을 추가한다.

Issue 본문 기대 형식 (이슈 템플릿의 textarea):

```json
{
  "prompt_id": "auto_korean_food_001",
  "prompt_text": "...",
  "tag": "food",
  "seed": 123456789,
  "inference_steps": 4,
  "source_filename": "img_20260615_auto_korean_food_001_cand_02.png",
  "note": ""
}
```
"""

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_json, save_json, get_logger

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
        logger.finalize("failed", {"stage": "parse_favorite_issue", "error": "empty issue body"})
        sys.exit(1)

    try:
        payload = extract_json_block(ISSUE_BODY)
    except Exception as e:
        logger.error(f"JSON 파싱 실패: {e}")
        logger.finalize("failed", {"stage": "parse_favorite_issue", "error": str(e)})
        sys.exit(1)

    required = ["prompt_text", "seed"]
    missing = [k for k in required if payload.get(k) is None]
    if missing:
        logger.error(f"필수 필드 누락: {missing}")
        logger.finalize("failed", {"stage": "parse_favorite_issue", "error": f"missing fields: {missing}"})
        sys.exit(1)

    favorites = load_json(DATA_DIR / "favorites.json", default={"favorites": []})

    entry = {
        "id": f"fav_{uuid.uuid4().hex[:8]}",
        "prompt_id": payload.get("prompt_id"),
        "prompt_text": payload["prompt_text"],
        "tag": payload.get("tag"),
        "seed": payload["seed"],
        "inference_steps": payload.get("inference_steps", 4),
        "source_filename": payload.get("source_filename"),
        "note": payload.get("note", ""),
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    favorites["favorites"].append(entry)
    save_json(DATA_DIR / "favorites.json", favorites)

    logger.info(f"즐겨찾기 추가됨: {entry['id']}")
    logger.finalize("success", {"stage": "parse_favorite_issue", "favorite_id": entry["id"]})


if __name__ == "__main__":
    main()
