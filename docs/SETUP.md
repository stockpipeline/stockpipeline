# 설치 가이드

## 1. GitHub 저장소 만들기

1. github.com에서 New repository
2. 이름: 자유 (예: stock-pipeline)
3. **Public** 선택 (Actions 무제한 무료 조건)
4. 이 폴더의 모든 파일을 저장소에 push

```bash
git init
git add .
git commit -m "initial setup"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

## 2. GitHub Secrets 등록

저장소 → Settings → Secrets and variables → Actions → New repository secret

### 필수 (없으면 파이프라인이 첫 단계에서 멈춤)

| Secret 이름 | 값 | 발급 위치 |
|---|---|---|
| `HF_TOKEN` | Hugging Face Read 토큰 | huggingface.co/settings/tokens |
| `GEMINI_API_KEY` | Gemini API 키 | aistudio.google.com/apikey |
| `ADMIN_PASSWORD` | 대시보드 접속 비밀번호 (직접 정하기) | - |

### 선택 (없으면 해당 기능만 자동 스킵, 파이프라인은 계속 진행)

| Secret 이름 | 값 | 비고 |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Cloud 서비스 계정 키 (JSON 전체) | Drive 업로드/백업용 |
| `GOOGLE_DRIVE_FOLDER_ID` | 원본 보관용 Drive 폴더 ID | URL의 `/folders/`뒤 부분 |
| `GOOGLE_DRIVE_BACKUP_FOLDER_ID` | 주간 백업용 Drive 폴더 ID | |
| `GMAIL_SERVICE_ACCOUNT_JSON` | Gmail 읽기용 서비스 계정 키 | 승인/반려 이메일 파싱용 |
| `GMAIL_USER` | 알림 수신용 Gmail 주소 | |
| `ADOBE_FTP_HOST` / `ADOBE_FTP_USER` / `ADOBE_FTP_PASS` | Adobe Stock Contributor FTP 정보 | Contributor 포털에서 확인 |
| `SHUTTERSTOCK_FTP_HOST` / `SHUTTERSTOCK_FTP_USER` / `SHUTTERSTOCK_FTP_PASS` | Shutterstock FTP 정보 | |
| `FREEPIK_API_KEY` | Freepik Sell Content API 키 | |

> 처음에는 필수 3개만 등록하고 시작해도 됩니다. 나머지는 해당 계정을 만들고 나서
> 하나씩 추가하면 됩니다 — Secret을 추가하는 순간부터 그 기능이 자동으로 켜집니다.

## 3. GitHub Pages 활성화

저장소 → Settings → Pages
- Source: **GitHub Actions** 선택

## 4. 대시보드 배포

Actions 탭 → "Deploy Dashboard" → Run workflow (수동 1회 실행)

완료되면 `https://<username>.github.io/<repo-name>/` 로 접속해서
설정한 ADMIN_PASSWORD로 로그인되는지 확인합니다.

## 5. 파이프라인 1회 테스트

Actions 탭 → "Daily Pipeline" → Run workflow

처음에는 Secrets가 일부만 있으므로 이미지 생성까지만 진행되고
업로드 단계는 자동 스킵됩니다 (로그에 "계정 정보 없음 - 스킵" 표시).
review_queue.json에 항목이 쌓이는지 대시보드 "검수" 탭에서 확인하세요.

## 6. Google 서비스 계정 만들기 (Drive/Gmail 연동용)

1. console.cloud.google.com → 새 프로젝트 생성
2. API 및 서비스 → 라이브러리 → "Google Drive API", "Gmail API" 활성화
3. API 및 서비스 → 사용자 인증 정보 → 서비스 계정 만들기
4. 키 생성 → JSON 다운로드
5. JSON 파일 내용 전체를 `GOOGLE_SERVICE_ACCOUNT_JSON` Secret에 붙여넣기
6. Drive: 서비스 계정 이메일을 대상 폴더에 "편집자"로 공유 추가
7. Gmail: Google Workspace가 아닌 일반 Gmail은 도메인 위임이 제한적이므로,
   초기에는 Gmail 연동을 생략하고 결과는 관리 페이지에서 수동으로 반영해도 됩니다
   (이메일 파싱은 best-effort 기능입니다)

## 진행 순서 요약

```
1. 저장소 생성 + push
2. 필수 Secrets 3개 등록 (HF_TOKEN, GEMINI_API_KEY, ADMIN_PASSWORD)
3. Pages 활성화 + Deploy Dashboard 실행
4. Daily Pipeline 수동 실행 → 이미지 생성 확인
5. Freepik 가입 + W-8BEN → FREEPIK_API_KEY 추가 → Freepik 자동 업로드 시작
6. Freepik 승인율 70% 달성 → 대시보드에서 Shutterstock 활성화
7. Shutterstock 승인율 70% 달성 → 대시보드에서 Adobe Stock 활성화
```
