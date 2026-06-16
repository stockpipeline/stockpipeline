# Stock Pipeline

AI 스톡 이미지 반자동화 시스템. 한식/한국문화/일러스트 등 카테고리별 프롬프트를
자동 생성하고, Colab(무료 GPU)에서 SDXL-Turbo로 이미지를 생성한 뒤
사용자가 대시보드에서 후보를 선택/검수하면 Adobe Stock / Freepik에 자동 업로드합니다.

## 전체 흐름

```
[자동] 01단계: 프롬프트 생성 (매일 새벽 3시, GitHub Actions + Gemini API)
               또는 대시보드 "프롬프트" 탭에서 즉석 주제 추가 가능

[사람] Colab 실행: generate_images.ipynb 열고 "모두 실행"
       → SDXL-Turbo로 후보 이미지 생성 + 필터 → GitHub push

[사람] 대시보드 "후보 선택" 탭: 후보 중 선택 / ⭐즐겨찾기 / 🔍정밀재생성
       → "선택 완료" → GitHub Issue 제출

[자동] Post-process: 03(업스케일/누끼) + 04(메타데이터/태그) + 05(검수큐 등록)
       → 항목별 검수 Issue 자동 생성 (GitHub 알림)

[사람] 검수: 대시보드 "검수" 탭 또는 GitHub Issue에 approve/reject 댓글

[자동] Upload: "Upload Approved Items" 워크플로우 실행
       → Adobe Stock(FTP) + Freepik(API) 업로드
```

## 폴더 구조

```
stock-pipeline/
├── config.json              # 전체 설정 (이 파일만 수정하면 대부분 조정 가능)
├── requirements.txt
├── colab/
│   ├── generate_images.ipynb  # 이미지 생성 노트북 (매일 실행)
│   └── prompt_lab.ipynb       # 프롬프트 실험실 (설정 튜닝용)
├── scripts/
│   ├── common.py
│   ├── 01_generate_prompts.py   # 프롬프트 생성
│   ├── 03_upscale_cutout.py     # 업스케일 + 누끼
│   ├── 04_generate_metadata.py  # 태그/제목 생성
│   ├── 05_save_and_queue.py     # 검수큐 등록
│   ├── 06_upload.py             # Adobe/Freepik 업로드
│   ├── 07_check_platform_results.py  # 플랫폼 결과 확인
│   ├── 08_weekly_tasks.py       # 주간 정리/백업
│   ├── create_review_issues.py  # 검수 Issue 자동 생성
│   ├── parse_*_issue.py         # Issue 파싱 스크립트들
│   └── process_review_comment.py
├── data/                    # JSON 데이터 (자동 생성/갱신)
├── thumbnails/              # 검수용 썸네일
├── site/                    # 관리 대시보드 (GitHub Pages)
└── .github/
    ├── workflows/
    │   ├── daily_pipeline.yml          # 매일 새벽 3시 프롬프트 생성
    │   ├── postprocess_selected.yml    # 선택 후 03~05단계 처리
    │   ├── process_candidate_selection.yml  # Issue 이벤트 처리
    │   ├── process_review_comment.yml  # 검수 댓글 처리
    │   ├── upload_approved.yml         # 승인 항목 업로드
    │   ├── deploy_dashboard.yml        # 대시보드 배포
    │   ├── weekly_tasks.yml            # 주간 작업
    │   └── setup_labels.yml            # 라벨 초기 설정 (1회)
    └── ISSUE_TEMPLATE/
        ├── candidate-selection.yml
        ├── custom-topic-request.yml
        ├── favorite-add.yml
        ├── refine-request.yml
        └── review-decision.yml

## 플랫폼

| 플랫폼 | 상태 | 비고 |
|---|---|---|
| Freepik | ✅ 활성 | PNG(누끼) 업로드, API |
| Adobe Stock | 🔒 대기 중 | Freepik 승인율 70% 달성 시 해금, FTP |
| Shutterstock | ❌ 영구 제외 | 2025-07-16부터 AI 생성 콘텐츠 전면 거부 |

## GitHub Secrets 필요 목록

```
GEMINI_API_KEY          # 프롬프트 생성 + 메타데이터 + Vision 체크
ADMIN_PASSWORD          # 대시보드 접속 비밀번호
FREEPIK_API_KEY         # Freepik 업로드
ADOBE_FTP_HOST          # Adobe Stock FTP (해금 후)
ADOBE_FTP_USER
ADOBE_FTP_PASS
GOOGLE_SERVICE_ACCOUNT_JSON  # Drive 백업 (선택)
GOOGLE_DRIVE_FOLDER_ID       # Drive 백업 (선택)
GMAIL_SERVICE_ACCOUNT_JSON   # 플랫폼 결과 이메일 파싱 (선택)
GMAIL_USER                   # (선택)
```

## Colab 노트북 주소

- 운영: https://colab.research.google.com/github/stockpipeline/stockpipeline/blob/main/colab/generate_images.ipynb
- 실험: https://colab.research.google.com/github/stockpipeline/stockpipeline/blob/main/colab/prompt_lab.ipynb
