"""
7단계: 플랫폼 결과 확인 (승인/반려 이메일 파싱)

흐름:
  1. 전용 Gmail 계정에서 Adobe/Freepik의 승인/반려 알림 메일을 읽음
     (Shutterstock: 2025-07-16부터 AI 생성 콘텐츠 전면 거부 - 제외)
  2. 파싱 성공 시 prompt_performance.json 업데이트
     - approved / rejected 카운트
     - 반려 3회 누적 시 해당 프롬프트 자동 비활성화 (prompts.json active=false)
  3. 플랫폼별 승인율 계산 → config.json platforms.*.approval_rate 갱신
  4. 승인율이 unlock_threshold를 넘으면 다음 플랫폼 enabled 후보로 표시
  5. 이메일 파싱 실패 시에도 파이프라인은 정상 종료
"""

import base64
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA_DIR, load_config, load_json, save_json, save_config, get_logger

GMAIL_SERVICE_ACCOUNT_JSON = os.environ.get("GMAIL_SERVICE_ACCOUNT_JSON", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")

PERF_PATH = DATA_DIR / "prompt_performance.json"
PROMPTS_PATH = DATA_DIR / "prompts.json"

# 플랫폼별 이메일 패턴 (제목/발신자 기준으로 단순 키워드 매칭)
# Shutterstock: AI 생성 콘텐츠 전면 거부(2025-07-16) - 제외
EMAIL_PATTERNS = {
    "adobe": {
        "from_contains": "stock.adobe.com",
        "approved_subject": ["approved", "has been accepted"],
        "rejected_subject": ["rejected", "not approved", "declined"],
    },
    "freepik": {
        "from_contains": "freepik.com",
        "approved_subject": ["approved", "published"],
        "rejected_subject": ["rejected", "declined"],
    },
}

# 파일명에서 프롬프트ID 추출: img_YYYYMMDD_p042_orig_001 -> p042
FILENAME_PATTERN = re.compile(r"img_\d{8}_([a-zA-Z0-9_]+?)_(orig|cutout)_\d{3}")


def extract_prompt_id(text: str) -> str:
    m = FILENAME_PATTERN.search(text)
    return m.group(1) if m else None


# ── Gmail 연동 ────────────────────────────────────────
def get_gmail_service():
    if not GMAIL_SERVICE_ACCOUNT_JSON or not GMAIL_USER:
        return None
    try:
        import json
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(GMAIL_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            subject=GMAIL_USER,
        )
        return build("gmail", "v1", credentials=creds)
    except Exception:
        return None


def fetch_recent_messages(service, query: str, max_results: int = 50) -> list:
    try:
        res = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        return res.get("messages", [])
    except Exception:
        return []


def get_message_detail(service, msg_id: str) -> dict:
    try:
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="metadata",
            metadataHeaders=["Subject", "From"]
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        snippet = msg.get("snippet", "")
        return {"subject": headers.get("Subject", ""), "from": headers.get("From", ""), "snippet": snippet}
    except Exception:
        return {}


# ── 이메일 파싱 → 결과 집계 ───────────────────────────────
def parse_results(service, logger) -> dict:
    """
    플랫폼별 {approved: [prompt_ids], rejected: [(prompt_id, reason)]}
    """
    results = {p: {"approved": [], "rejected": []} for p in EMAIL_PATTERNS}

    if service is None:
        logger.warn("Gmail 연동 정보 없음 - 결과 자동 확인 스킵")
        return results

    for platform, pattern in EMAIL_PATTERNS.items():
        query = f"from:{pattern['from_contains']} newer_than:2d"
        messages = fetch_recent_messages(service, query)

        for m in messages:
            detail = get_message_detail(service, m["id"])
            subject = detail.get("subject", "").lower()
            snippet = detail.get("snippet", "")

            prompt_id = extract_prompt_id(subject) or extract_prompt_id(snippet)
            if not prompt_id:
                continue

            if any(k in subject for k in pattern["approved_subject"]):
                results[platform]["approved"].append(prompt_id)
            elif any(k in subject for k in pattern["rejected_subject"]):
                reason = "similar_content" if "similar" in snippet.lower() else "quality"
                results[platform]["rejected"].append((prompt_id, reason))

        logger.info(
            f"{platform}: 승인 {len(results[platform]['approved'])}건, "
            f"반려 {len(results[platform]['rejected'])}건 감지"
        )

    return results


# ── 성과 업데이트 + 자동 비활성화 ─────────────────────────
def update_performance(results: dict, config: dict, logger):
    performance = load_json(PERF_PATH, default={})
    prompts_data = load_json(PROMPTS_PATH, default={"prompts": []})
    prompts = prompts_data.get("prompts", [])
    rejection_limit = config["prompt_evolution"]["rejection_limit"]

    deactivated = []

    for platform, data in results.items():
        for prompt_id in data["approved"]:
            perf = performance.setdefault(prompt_id, {})
            perf["approved"] = perf.get("approved", 0) + 1

        for prompt_id, reason in data["rejected"]:
            perf = performance.setdefault(prompt_id, {})
            perf["rejected"] = perf.get("rejected", 0) + 1
            perf.setdefault("reject_reasons", []).append(reason)

            if perf["rejected"] >= rejection_limit:
                for p in prompts:
                    if p["id"] == prompt_id and p.get("active", True):
                        p["active"] = False
                        deactivated.append(prompt_id)
                        logger.warn(f"프롬프트 {prompt_id} 반려 {perf['rejected']}회 → 자동 비활성화")

    save_json(PERF_PATH, performance)
    save_json(PROMPTS_PATH, prompts_data)
    return deactivated


# ── 플랫폼 승인율 갱신 + 해금 후보 표시 ─────────────────────
def update_platform_unlock(results: dict, config: dict, logger):
    platforms = config["platforms"]

    for platform, data in results.items():
        approved = len(data["approved"])
        rejected = len(data["rejected"])
        total = approved + rejected
        if total == 0:
            continue

        # 기존 데이터와 합산 (단순 누적 비율)
        prev = platforms[platform].get("approval_rate", 0)
        # 단순화: 최근 배치 기준으로 갱신 (실제로는 누적 카운트 별도 저장이 더 정확하지만
        # 여기서는 review_queue 기반 누적치를 prompt_performance에서 재계산)
        platforms[platform]["approval_rate"] = round(approved / total, 3)

    # 다음 플랫폼 해금 후보 체크
    for platform, pconf in platforms.items():
        unlock_after = pconf.get("unlock_after")
        if not unlock_after or pconf.get("enabled"):
            continue
        prev_rate = platforms[unlock_after].get("approval_rate", 0)
        threshold = pconf.get("unlock_threshold", 1.0)
        if prev_rate >= threshold:
            logger.success(
                f"{platform} 해금 가능: {unlock_after} 승인율 {prev_rate:.0%} "
                f"(기준 {threshold:.0%}) 달성"
            )
            pconf["unlock_ready"] = True

    save_config(config)


# ── 메인 ──────────────────────────────────────────────
def main():
    logger = get_logger()
    config = load_config()

    service = get_gmail_service()
    results = parse_results(service, logger)

    deactivated = update_performance(results, config, logger)
    update_platform_unlock(results, config, logger)

    total_approved = sum(len(r["approved"]) for r in results.values())
    total_rejected = sum(len(r["rejected"]) for r in results.values())

    logger.finalize("success", {
        "stage": "platform_results",
        "gmail_connected": service is not None,
        "approved": total_approved,
        "rejected": total_rejected,
        "deactivated_prompts": deactivated,
    })


if __name__ == "__main__":
    main()
