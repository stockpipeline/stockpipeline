"""
5단계: 저장 (Google Drive 원본 + GitHub 썸네일)

흐름:
  1. 원본(업스케일 JPG + 누끼 PNG)을 Google Drive에 날짜별 폴더로 업로드
  2. 200x200 썸네일을 생성해 /thumbnails/ 에 저장 (관리 페이지에서 검수용으로 사용)
  3. 30일 지난 썸네일 자동 삭제
  4. 검수 대기 목록(review_queue.json) 생성
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    DATA_DIR, UPSCALED_DIR, CUTOUT_DIR, THUMBNAILS_DIR,
    load_config, load_json, save_json, get_logger, today_str
)

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

THUMB_SIZE = (200, 200)


# ── Google Drive 업로드 ──────────────────────────────────
def get_drive_service():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.file"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception:
        return None


def ensure_date_folder(service, parent_id: str, date_str: str, logger) -> str:
    query = (
        f"'{parent_id}' in parents and name='{date_str}' "
        "and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = service.files().list(q=query, fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": date_str,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    logger.info(f"Drive 폴더 생성: {date_str}")
    return folder["id"]


def upload_to_drive(service, folder_id: str, file_path: Path, logger) -> str:
    from googleapiclient.http import MediaFileUpload

    metadata = {"name": file_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(file_path), resumable=False)
    try:
        f = service.files().create(body=metadata, media_body=media, fields="id").execute()
        return f.get("id", "")
    except Exception as e:
        logger.warn(f"Drive 업로드 실패({file_path.name}): {e}")
        return ""


# ── 썸네일 생성 ────────────────────────────────────────
def make_thumbnail(src_path: Path, dst_path: Path):
    img = Image.open(src_path).convert("RGB")
    img.thumbnail(THUMB_SIZE)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst_path, format="JPEG", quality=80)


# ── 30일 지난 썸네일 정리 ──────────────────────────────────
def cleanup_old_thumbnails(retention_days: int, logger):
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    if not THUMBNAILS_DIR.exists():
        return removed

    for date_dir in THUMBNAILS_DIR.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            dir_date = datetime.strptime(date_dir.name, "%Y%m%d")
        except ValueError:
            continue
        if dir_date < cutoff:
            for f in date_dir.glob("*"):
                f.unlink()
            date_dir.rmdir()
            removed += 1

    if removed:
        logger.info(f"{removed}일치 썸네일 폴더 삭제 (30일 경과)")
    return removed


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()
    config = load_config()

    metadata_results = load_json(DATA_DIR / "metadata_results.json", default={"images": []})["images"]
    if not metadata_results:
        logger.warn("저장할 이미지가 없습니다")
        logger.finalize("partial", {"stage": "storage", "saved": 0})
        return

    date_str = today_str()
    thumb_dir = THUMBNAILS_DIR / date_str

    drive_service = get_drive_service()
    drive_folder_id = None
    if drive_service and GOOGLE_DRIVE_FOLDER_ID:
        drive_folder_id = ensure_date_folder(drive_service, GOOGLE_DRIVE_FOLDER_ID, date_str, logger)
    else:
        logger.warn("Google Drive 연동 정보 없음 - Drive 업로드 스킵")

    review_queue = []

    for item in metadata_results:
        jpg_path = UPSCALED_DIR / item["orig_jpg"]
        png_path = CUTOUT_DIR / item["cutout_png"]

        drive_ids = {}

        # Drive 업로드
        if drive_service and drive_folder_id:
            if jpg_path.exists():
                drive_ids["orig_jpg"] = upload_to_drive(drive_service, drive_folder_id, jpg_path, logger)
            if png_path.exists():
                drive_ids["cutout_png"] = upload_to_drive(drive_service, drive_folder_id, png_path, logger)

        # 썸네일 생성
        thumb_jpg = None
        thumb_png = None
        if jpg_path.exists():
            thumb_jpg = f"{item['orig_jpg'].rsplit('.', 1)[0]}_thumb.jpg"
            make_thumbnail(jpg_path, thumb_dir / thumb_jpg)
        if png_path.exists():
            thumb_png = f"{item['cutout_png'].rsplit('.', 1)[0]}_thumb.jpg"
            make_thumbnail(png_path, thumb_dir / thumb_png)

        review_queue.append({
            "prompt_id": item["prompt_id"],
            "tag": item["tag"],
            "title": item["title"],
            "keywords": item.get("keywords", []),
            "orig_jpg": item["orig_jpg"],
            "cutout_png": item["cutout_png"],
            "thumb_orig": f"{date_str}/{thumb_jpg}" if thumb_jpg else None,
            "thumb_cutout": f"{date_str}/{thumb_png}" if thumb_png else None,
            "drive_ids": drive_ids,
            "upload_targets": {
                "adobe": "orig_jpg",
                "freepik": "cutout_png",
                # shutterstock: 2025-07-16 AI 생성 콘텐츠 전면 거부 - 제외
            },
            "review_status": "pending",  # pending | approved | rejected
            "reject_reason": None,
            "date": date_str,
            "review_issue_number": None,  # Issue 알림 방식 사용 시 채워짐
        })

    # 30일 지난 썸네일 정리
    cleanup_old_thumbnails(config["storage"]["thumbnail_retention_days"], logger)

    # 기존 검수 대기열에 추가 (누적)
    existing_queue = load_json(DATA_DIR / "review_queue.json", default={"items": []})
    existing_queue["items"] = review_queue + existing_queue.get("items", [])
    save_json(DATA_DIR / "review_queue.json", existing_queue)

    logger.success(f"{len(review_queue)}장 저장 및 검수 대기열 등록 완료")

    logger.finalize("success", {
        "stage": "storage",
        "saved": len(review_queue),
        "drive_connected": drive_service is not None,
    })


if __name__ == "__main__":
    main()
