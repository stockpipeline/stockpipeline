"""
review-decision-item 라벨이 붙은 Issue에 'approve' 또는 'reject [이유]'
댓글이 달리면, review_queue.json의 해당 항목(issue_number로 매칭)을
갱신하고 Issue를 닫는다.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_json, save_json, get_logger

ISSUE_NUMBER = int(os.environ.get("ISSUE_NUMBER", "0"))
COMMENT_BODY = os.environ.get("COMMENT_BODY", "").strip().lower()


def main():
    logger = get_logger()

    if not ISSUE_NUMBER:
        logger.error("ISSUE_NUMBER가 비어있습니다")
        logger.finalize("failed", {"stage": "process_review_comment", "error": "missing issue number"})
        sys.exit(1)

    m = re.match(r"^(approve|reject)\b\s*(.*)$", COMMENT_BODY)
    if not m:
        logger.info(f"인식 가능한 명령이 아님 (무시): {COMMENT_BODY[:50]}")
        logger.finalize("success", {"stage": "process_review_comment", "action": "ignored"})
        return

    action, rest = m.group(1), m.group(2).strip()

    queue = load_json(DATA_DIR / "review_queue.json", default={"items": []})
    items = queue.get("items", [])

    target = None
    for item in items:
        if item.get("review_issue_number") == ISSUE_NUMBER:
            target = item
            break

    if not target:
        logger.warn(f"Issue #{ISSUE_NUMBER}에 해당하는 review_queue 항목 없음")
        logger.finalize("success", {"stage": "process_review_comment", "action": "not_found"})
        return

    if target.get("review_status") != "pending":
        logger.warn(f"이미 처리된 항목: {target.get('orig_jpg')} (status={target.get('review_status')})")
        logger.finalize("success", {"stage": "process_review_comment", "action": "already_processed"})
        return

    if action == "approve":
        target["review_status"] = "approved"
    else:
        target["review_status"] = "rejected"
        target["reject_reason"] = rest or "other"

    save_json(DATA_DIR / "review_queue.json", queue)

    logger.info(f"검수 반영: {target.get('orig_jpg')} -> {target['review_status']}")
    logger.finalize("success", {
        "stage": "process_review_comment",
        "orig_jpg": target.get("orig_jpg"),
        "status": target["review_status"],
    })


if __name__ == "__main__":
    main()
