"""
GitHub Issue(review-decision 라벨)의 본문에서 JSON을 추출해
data/review_queue.json의 항목들을 갱신한다.

Issue 본문 기대 형식:

```json
{
  "decisions": [
    {"orig_jpg": "img_..._orig_001.jpg", "status": "approved"},
    {"orig_jpg": "img_..._orig_002.jpg", "status": "rejected", "reject_reason": "quality"},
    ...
  ]
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

ISSUE_BODY = os.environ.get("ISSUE_BODY", "")

VALID_STATUSES = {"approved", "rejected"}


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
        logger.finalize("failed", {"stage": "parse_review_issue", "error": "empty issue body"})
        sys.exit(1)

    try:
        payload = extract_json_block(ISSUE_BODY)
    except Exception as e:
        logger.error(f"JSON 파싱 실패: {e}")
        logger.finalize("failed", {"stage": "parse_review_issue", "error": str(e)})
        sys.exit(1)

    decisions = payload.get("decisions", [])
    if not decisions:
        logger.warn("결정 항목이 없습니다")

    queue = load_json(DATA_DIR / "review_queue.json", default={"items": []})
    items_by_key = {item["orig_jpg"]: item for item in queue.get("items", []) if "orig_jpg" in item}

    updated = 0
    for d in decisions:
        key = d.get("orig_jpg")
        status = d.get("status")
        if not key or status not in VALID_STATUSES:
            logger.warn(f"잘못된 결정 항목 스킵: {d}")
            continue

        item = items_by_key.get(key)
        if not item:
            logger.warn(f"review_queue에 없는 항목: {key}")
            continue

        if item.get("review_status") != "pending":
            logger.warn(f"이미 처리된 항목 스킵: {key} (status={item.get('review_status')})")
            continue

        item["review_status"] = status
        if status == "rejected":
            item["reject_reason"] = d.get("reject_reason", "other")
        updated += 1

    save_json(DATA_DIR / "review_queue.json", queue)

    logger.info(f"검수 결과 반영: {updated}개")
    logger.finalize("success", {"stage": "parse_review_issue", "updated": updated})


if __name__ == "__main__":
    main()
