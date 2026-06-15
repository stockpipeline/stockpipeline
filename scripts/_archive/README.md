# Archive

이 폴더의 파일들은 더 이상 워크플로우에서 사용되지 않지만,
참고/복원을 위해 남겨둔 코드입니다.

## 02_generate_images_imagen4.py.bak

- HF Inference Providers → Pollinations.ai → Imagen 4 순으로 이미지 생성
  방식을 시도했던 코드의 최종 버전 (Imagen 4 기반).
- Imagen 4는 2025년 12월부터 무료 티어에서 이미지 생성이 0으로
  제한되어 (billing 활성화 필수) 사용 불가능으로 확인됨.
- 최종적으로 이미지 생성은 **Colab + SDXL-Turbo**
  (colab/generate_images.ipynb, 무료 GPU, 사람이 실행)로 대체됨.
- 새 흐름: Colab → candidates.json → 대시보드에서 선택(Issue) →
  selections.json → 03_upscale_cutout.py (postprocess_selected.yml)
