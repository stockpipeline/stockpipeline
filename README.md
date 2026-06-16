# Stock Pipeline

한식/한국문화 중심 AI 스톡 이미지 반자동화 시스템.

## 흐름

```
[자동] 프롬프트 생성 (매일 새벽 3시)
[사람] Colab에서 이미지 생성 → 대시보드에서 후보 선택/검수
[자동] 업스케일 + 메타데이터 생성 + Adobe/Freepik 업로드
```

## Colab 노트북

- [이미지 생성](https://colab.research.google.com/github/stockpipeline/stockpipeline/blob/main/colab/generate_images.ipynb)
- [프롬프트 실험실](https://colab.research.google.com/github/stockpipeline/stockpipeline/blob/main/colab/prompt_lab.ipynb)

## 대시보드

https://stockpipeline.github.io/stockpipeline/
