"""
공통 유틸리티 모듈
설정 로드, 로깅, 디렉토리 관리 등 모든 모듈에서 공통으로 쓰는 기능
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 경로 정의 ──────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
DATA_DIR = ROOT_DIR / "data"
THUMBNAILS_DIR = ROOT_DIR / "thumbnails"

# 작업용 임시 디렉토리 (Actions 실행 중에만 존재)
WORK_DIR = Path(os.environ.get("PIPELINE_WORK_DIR", "/tmp/pipeline_work"))

RAW_DIR = WORK_DIR / "1_raw"
UPSCALED_DIR = WORK_DIR / "2_upscaled"
CUTOUT_DIR = WORK_DIR / "3_cutout"
READY_DIR = WORK_DIR / "4_ready"

KST = timezone(timedelta(hours=9))


# ── 설정 로드 ──────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ── JSON 데이터 헬퍼 ────────────────────────────────────
def load_json(path: Path, default=None):
    if not Path(path).exists():
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 디렉토리 준비 ──────────────────────────────────────
def prepare_work_dirs():
    for d in [RAW_DIR, UPSCALED_DIR, CUTOUT_DIR, READY_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── 시간 헬퍼 ──────────────────────────────────────────
def now_kst() -> datetime:
    return datetime.now(KST)


def today_str() -> str:
    return now_kst().strftime("%Y%m%d")


def timestamp_str() -> str:
    return now_kst().strftime("%Y%m%d_%H%M%S")


# ── 로깅 ──────────────────────────────────────────────
class Logger:
    """
    실행 로그를 콘솔 + run_log.json에 동시에 남긴다.
    run_log.json은 관리 페이지 대시보드가 읽어서 상태를 표시한다.
    """

    def __init__(self):
        self.entries = []
        self.status = "running"
        self.summary = {}

    def log(self, message: str, level: str = "info"):
        ts = now_kst().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        print(line, flush=True)
        self.entries.append({"time": ts, "level": level, "message": message})

    def info(self, msg): self.log(msg, "info")
    def warn(self, msg): self.log(msg, "warn")
    def error(self, msg): self.log(msg, "error")
    def success(self, msg): self.log(msg, "success")

    def finalize(self, status: str, summary: dict):
        """
        status: "success" | "partial" | "failed"
        summary: 관리 페이지에 표시할 핵심 지표
        """
        self.status = status
        self.summary = summary

        run_log_path = DATA_DIR / "run_log.json"
        existing = load_json(run_log_path, default={"history": []})

        record = {
            "timestamp": now_kst().isoformat(),
            "status": status,
            "summary": summary,
            "logs": self.entries[-50:],  # 최근 50줄만 보관
        }

        existing["latest"] = record
        existing.setdefault("history", [])
        existing["history"].insert(0, record)
        existing["history"] = existing["history"][:30]  # 최근 30일치만

        save_json(run_log_path, existing)
        self.info(f"실행 결과 저장 완료 (status={status})")


def get_logger() -> Logger:
    return Logger()


# ── 파일명 규칙 ────────────────────────────────────────
def make_filename(prompt_id: str, variant: str, seq: int, ext: str) -> str:
    """
    img_{날짜}_{프롬프트ID}_{variant}_{일련번호}.{ext}
    variant: "orig" | "cutout"
    예: img_20260614_p042_orig_001.png
    """
    return f"img_{today_str()}_{prompt_id}_{variant}_{seq:03d}.{ext}"


# ── Gemini 호출 공통 재시도 헬퍼 ──────────────────────────
def gemini_generate_with_retry(model, contents, logger=None, max_retries=3, base_wait=65):
    """
    Gemini 무료 티어 분당 요청 한도(429) 대응.
    429 발생 시 base_wait초 대기 후 재시도, max_retries회까지.
    그 외 예외는 즉시 raise (호출부에서 처리).
    """
    import time as _time

    for attempt in range(max_retries):
        try:
            return model.generate_content(contents)
        except Exception as e:
            if "429" in str(e) and attempt < max_retries - 1:
                if logger:
                    logger.warn(f"Gemini 429 (분당 한도) - {base_wait}초 대기 후 재시도 ({attempt+1}/{max_retries})")
                _time.sleep(base_wait)
                continue
            raise


if __name__ == "__main__":
    cfg = load_config()
    print("Config loaded OK. daily_prompt_count =", cfg["daily_prompt_count"])
