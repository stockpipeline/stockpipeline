"""
주간 작업 (매주 월요일 새벽, 일일 파이프라인 이후 실행)

1. 핵심 JSON 파일들을 Google Drive에 백업
2. 각 플랫폼 정책/공지 페이지 크롤링 → 변경 감지 → policy_updates.json
"""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_json, save_json, get_logger, now_kst

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_DRIVE_BACKUP_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_BACKUP_FOLDER_ID", "")

BACKUP_FILES = [
    "prompts.json",
    "prompt_performance.json",
    "phash_db.json",
    "review_queue.json",
    "tag_blacklist.json",
]

POLICY_URLS = {
    "adobe": "https://helpx.adobe.com/stock/contributor/help/generative-ai-content.html",
    "shutterstock": "https://supportforcontributors.shutterstock.com/s/article/Submitting-AI-Generated-Content",
    "freepik": "https://support.freepik.com/s/article/AI-generated-content-policy",
}


# ── Drive 백업 ────────────────────────────────────────
def backup_to_drive(logger):
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_DRIVE_BACKUP_FOLDER_ID:
        logger.warn("Drive 백업 설정 없음 - 스킵")
        return False

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.file"]
        )
        service = build("drive", "v3", credentials=creds)

        date_str = now_kst().strftime("%Y%m%d")

        # 날짜별 백업 폴더 생성
        metadata = {
            "name": f"backup_{date_str}",
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [GOOGLE_DRIVE_BACKUP_FOLDER_ID],
        }
        folder = service.files().create(body=metadata, fields="id").execute()
        folder_id = folder["id"]

        for fname in BACKUP_FILES:
            fpath = DATA_DIR / fname
            if not fpath.exists():
                continue
            media = MediaFileUpload(str(fpath), resumable=False)
            service.files().create(
                body={"name": fname, "parents": [folder_id]},
                media_body=media, fields="id"
            ).execute()
            logger.info(f"백업: {fname}")

        logger.success(f"주간 백업 완료 → backup_{date_str}")
        return True
    except Exception as e:
        logger.warn(f"Drive 백업 실패: {e}")
        return False


# ── 정책 페이지 모니터링 ──────────────────────────────────
def check_policy_pages(logger) -> dict:
    prev = load_json(DATA_DIR / "policy_updates.json", default={"pages": {}})
    now_str = now_kst().isoformat()

    for platform, url in POLICY_URLS.items():
        try:
            res = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            content_hash = hashlib.sha256(res.content).hexdigest()
        except Exception as e:
            prev["pages"][platform] = prev["pages"].get(platform, {})
            prev["pages"][platform].update({
                "status": "fetch_failed",
                "error": str(e)[:100],
                "url": url,
                "checked_at": now_str,
            })
            logger.warn(f"{platform} 정책 페이지 확인 실패: {e}")
            continue

        page_info = prev["pages"].get(platform, {})
        old_hash = page_info.get("content_hash")

        changed = old_hash is not None and old_hash != content_hash

        prev["pages"][platform] = {
            "status": "changed" if changed else "ok",
            "content_hash": content_hash,
            "url": url,
            "checked_at": now_str,
            "last_changed_at": now_str if changed else page_info.get("last_changed_at"),
        }

        if changed:
            logger.warn(f"{platform} 정책 페이지 변경 감지!")
        else:
            logger.info(f"{platform} 정책 페이지 변경 없음")

    save_json(DATA_DIR / "policy_updates.json", prev)
    return prev


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()

    backup_ok = backup_to_drive(logger)
    policy_result = check_policy_pages(logger)

    changed_platforms = [
        p for p, info in policy_result["pages"].items()
        if info.get("status") == "changed"
    ]

    logger.finalize("success", {
        "stage": "weekly_tasks",
        "backup_ok": backup_ok,
        "policy_changed": changed_platforms,
    })


if __name__ == "__main__":
    main()
