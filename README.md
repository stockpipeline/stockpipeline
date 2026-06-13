# Stock Pipeline

AI 스톡 이미지 완전 자동화 시스템. 매일 새벽 GitHub Actions가 한식/한국문화/판타지/추상 등의
이미지를 생성 → 품질·중복 필터 → 4K 업스케일 → 누끼 생성 → 메타데이터 생성 →
검수 대기열 등록까지 자동으로 처리합니다. 사용자는 관리 대시보드에서 검수 승인만 하면
Adobe Stock / Shutterstock / Freepik에 자동 업로드됩니다.

## 폴더 구조

```
stock-pipeline/
├── config.json              # 전체 설정 (이 파일만 수정하면 대부분 조정 가능)
├── requirements.txt
├── scripts/
│   ├── common.py             # 공통 유틸
│   ├── 01_generate_prompts.py
│   ├── 02_generate_images.py
│   ├── 03_upscale_cutout.py
│   ├── 04_generate_metadata.py
│   ├── 05_save_and_queue.py
│   ├── 06_upload.py
│   ├── 07_check_platform_results.py
│   └── 08_weekly_tasks.py
├── data/                     # 모든 JSON 데이터 (자동 생성/갱신)
├── thumbnails/               # 검수용 썸네일 (30일 자동 삭제)
├── site/                     # 관리 대시보드 (GitHub Pages)
└── .github/workflows/
    ├── daily_pipeline.yml    # 매일 새벽 3시 (KST) 실행
    ├── weekly_tasks.yml      # 매주 월요일 백업 + 정책 확인
    └── deploy_dashboard.yml  # 대시보드 배포
```

## 설치 순서

자세한 내용은 `docs/SETUP.md` 참고. 요약:

1. 이 저장소를 Public으로 GitHub에 생성
2. GitHub Secrets에 API 키/계정 정보 입력 (`docs/SETUP.md` 목록 참고)
3. Settings → Pages에서 GitHub Actions를 소스로 설정
4. Actions 탭에서 `Deploy Dashboard` 워크플로우 1회 수동 실행
5. 발급받은 비밀번호로 대시보드 접속 확인
6. `daily_pipeline.yml`을 수동 실행(workflow_dispatch)해서 1회 테스트

## 설정 변경

대부분의 동작은 `config.json`에서 조정합니다. 코드를 건드릴 필요가 없습니다.

- `daily_prompt_count`: 하루 시도할 프롬프트 수
- `category_weights`: 카테고리별 비중
- `platforms.*.enabled`: 플랫폼 활성화 여부 (대시보드의 "지금 활성화" 버튼이 이 값을 바꿈)
- `review_mode`: "manual" (현재) → 나중에 "auto"로 전환 가능
- `modules.video`: 영상 모듈 추가 시 true로 전환

## 모듈 구조

영상 모듈, 신규 플랫폼 추가는 `config.json`의 `modules` / `platforms` 섹션에
새 항목을 추가하고 해당 스크립트만 작성하면 됩니다. 메타데이터·저장·알림은
공통 모듈을 그대로 재사용합니다.
