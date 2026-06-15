"""
review_queue.json의 review_status == "pending"이고
review_issue_number가 비어있는 항목에 대해, 이미지+메타데이터를 담은
GitHub Issue를 생성한다.

생성된 Issue의 번호는 review_queue.json에 기록되어, 같은 항목에 대해
중복으로 Issue가 생성되지 않도록 한다.

Issue에는 "review-decision-item" 라벨을 붙인다.
사람이 Issue에 'approve' 또는 'reject [이유]' 댓글을 달면,
별도 워크플로우(process_review_comment.yml)가 review_queue.json을 갱신한다.
"""

import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_json, save_json, get_logger

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo"

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPOSITORY}/main"
API_BASE = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/issues"

MAX_ISSUES_PER_RUN = 10  # 한 번 실행에서 너무 많은 Issue를 만들지 않도록 제한


def create_issue(title, body, labels, logger):
    res = requests.post(
        API_BASE,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={"title": title, "body": body, "labels": labels},
        timeout=30,
    )
    if res.status_code >= 300:
        logger.error(f"Issue 생성 실패 ({res.status_code}): {res.text[:300]}")
        return None
    return res.json()["number"]


def main():
    logger = get_logger()

    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logger.warn("GITHUB_TOKEN 또는 GITHUB_REPOSITORY 미설정 - Issue 생성 스킵")
        logger.finalize("partial", {"stage": "create_review_issues", "created": 0})
        return

    queue = load_json(DATA_DIR / "review_queue.json", default={"items": []})
    items = queue.get("items", [])

    created = 0
    for item in items:
        if item.get("review_status") != "pending":
            continue
        if item.get("review_issue_number"):
            continue
        if created >= MAX_ISSUES_PER_RUN:
            logger.info(f"이번 실행 Issue 생성 한도({MAX_ISSUES_PER_RUN}) 도달 - 나머지는 다음 실행에서")
            break

        thumb = item.get("thumb_orig")
        img_md = ""
        if thumb:
            img_url = f"{RAW_BASE}/thumbnails/{thumb}"
            img_md = f"![preview]({img_url})\n\n"

        keywords = item.get("keywords", [])
        keyword_str = ", ".join(keywords[:15]) + (" ..." if len(keywords) > 15 else "")

        body = (
            f"{img_md}"
            f"**제목**: {item.get('title', '')}\n\n"
            f"**카테고리**: {item.get('tag', '')}\n\n"
            f"**키워드 ({len(keywords)}개)**: {keyword_str}\n\n"
            f"**파일**: `{item.get('orig_jpg', '')}`\n\n"
            "---\n"
            "이 항목을 승인하려면 댓글에 `approve`,\n"
            "반려하려면 `reject [이유]` (예: `reject quality`)를 입력해주세요."
        )

        title = f"[검수] {item.get('title', item.get('orig_jpg', ''))}"
        issue_number = create_issue(title, body, ["review-decision-item"], logger)

        if issue_number:
            item["review_issue_number"] = issue_number
            created += 1
            logger.info(f"검수 Issue 생성됨: #{issue_number} ({item.get('orig_jpg')})")

    save_json(DATA_DIR / "review_queue.json", queue)

    logger.info(f"검수 Issue 생성 완료: {created}개")
    logger.finalize("success", {"stage": "create_review_issues", "created": created})


if __name__ == "__main__":
    main()
