"""
6단계: 업로드 (검수 승인된 항목만)

- review_queue.json에서 review_status == "approved" 인 항목만 처리
- 플랫폼 활성화 여부(config.json platforms.*.enabled)에 따라 분기
- Adobe Stock: FTP 업로드 (이미지 + CSV)
- Freepik: Sell Content API 업로드
- Shutterstock: 2025-07-16부터 AI 생성 콘텐츠 전면 거부 - 영구 제외
- 업로드 완료 후 review_queue에서 해당 항목 상태를 "uploaded"로 변경
"""

import csv
import ftplib
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    DATA_DIR, UPSCALED_DIR, CUTOUT_DIR,
    load_config, load_json, save_json, get_logger, today_str
)

ADOBE_FTP_HOST = os.environ.get("ADOBE_FTP_HOST", "ftp.contributor.adobestock.com")
ADOBE_FTP_USER = os.environ.get("ADOBE_FTP_USER", "")
ADOBE_FTP_PASS = os.environ.get("ADOBE_FTP_PASS", "")

FREEPIK_API_KEY = os.environ.get("FREEPIK_API_KEY", "")
FREEPIK_API_URL = "https://api.freepik.com/v1/resources"


# ── FTP 업로드 공통 ────────────────────────────────────
def ftp_upload(host: str, user: str, password: str, file_path: Path, logger) -> bool:
    if not user or not password:
        logger.warn(f"FTP 계정 정보 없음 ({host}) - 스킵")
        return False
    try:
        with ftplib.FTP(host, timeout=60) as ftp:
            ftp.login(user, password)
            with open(file_path, "rb") as f:
                ftp.storbinary(f"STOR {file_path.name}", f)
        return True
    except ftplib.all_errors as e:
        logger.warn(f"FTP 업로드 실패 ({file_path.name} -> {host}): {e}")
        return False


def ftp_upload_csv_row(host: str, user: str, password: str, csv_path: Path, logger) -> bool:
    return ftp_upload(host, user, password, csv_path, logger)


# ── Freepik API 업로드 ──────────────────────────────────
def freepik_upload(file_path: Path, title: str, keywords: list, logger) -> bool:
    if not FREEPIK_API_KEY:
        logger.warn("Freepik API 키 없음 - 스킵")
        return False

    headers = {"x-freepik-api-key": FREEPIK_API_KEY}
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "image/png")}
            data = {
                "title": title,
                "keywords": ",".join(keywords),
                "ai_generated": "true",
                "license": "free",
            }
            res = requests.post(FREEPIK_API_URL, headers=headers, files=files, data=data, timeout=120)
        if res.status_code in (200, 201):
            return True
        logger.warn(f"Freepik 업로드 실패 ({file_path.name}): {res.status_code} {res.text[:150]}")
        return False
    except Exception as e:
        logger.warn(f"Freepik 업로드 예외 ({file_path.name}): {e}")
        return False


# ── 플랫폼별 CSV에서 해당 파일의 메타 한 줄 추출 ─────────────
def load_csv_rows(csv_path: Path) -> dict:
    """filename -> row dict"""
    if not csv_path.exists():
        return {}
    rows = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows[row["Filename"]] = row
    return rows


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()
    config = load_config()

    queue = load_json(DATA_DIR / "review_queue.json", default={"items": []})
    items = queue.get("items", [])

    approved = [it for it in items if it.get("review_status") == "approved"]
    if not approved:
        logger.info("업로드할 승인 항목이 없습니다")
        logger.finalize("success", {"stage": "upload", "uploaded": 0})
        return

    platforms = config["platforms"]
    date_str = approved[0].get("date", today_str())
    csv_dir = DATA_DIR / "csv_output" / date_str

    adobe_rows = load_csv_rows(csv_dir / "adobe_stock.csv")
    fp_rows = load_csv_rows(csv_dir / "freepik.csv")
    # Shutterstock: 2025-07-16부터 AI 생성 콘텐츠 전면 거부 - 업로드 불가

    counts = {"adobe": 0, "freepik": 0}

    for item in approved:
        orig_jpg = item["orig_jpg"]
        cutout_png = item["cutout_png"]

        # Adobe Stock (FTP)
        if platforms["adobe"]["enabled"]:
            path = UPSCALED_DIR / orig_jpg
            if path.exists() and orig_jpg in adobe_rows:
                if ftp_upload(ADOBE_FTP_HOST, ADOBE_FTP_USER, ADOBE_FTP_PASS, path, logger):
                    counts["adobe"] += 1

        # Freepik (API)
        if platforms["freepik"]["enabled"]:
            path = CUTOUT_DIR / cutout_png
            if path.exists() and cutout_png in fp_rows:
                row = fp_rows[cutout_png]
                keywords = [k.strip() for k in row["Keywords"].split(",")]
                if freepik_upload(path, row["Title"], keywords, logger):
                    counts["freepik"] += 1

        item["review_status"] = "uploaded"

    # Adobe CSV도 FTP로 함께 전송 (메타데이터 일괄 매칭용)
    if platforms["adobe"]["enabled"] and (csv_dir / "adobe_stock.csv").exists():
        ftp_upload_csv_row(ADOBE_FTP_HOST, ADOBE_FTP_USER, ADOBE_FTP_PASS, csv_dir / "adobe_stock.csv", logger)

    save_json(DATA_DIR / "review_queue.json", queue)

    logger.success(
        f"업로드 완료 - Adobe:{counts['adobe']} Freepik:{counts['freepik']}"
    )

    logger.finalize("success", {
        "stage": "upload",
        "uploaded_total": sum(counts.values()),
        "by_platform": counts,
    })


if __name__ == "__main__":
    main()
