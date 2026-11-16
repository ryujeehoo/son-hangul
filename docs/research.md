# 2단계 조사: AI 손글씨 모델

2026-11-16 기준. 웹 검색으로 확인한 내용이며, 모델을 직접 돌려 보지는 않았다.
각 항목에 **확인함 / 확인 못 함**을 적었다. 확인 못 한 것은 쓰기 전에 원문을 직접 봐야 한다.

## 결론부터

- 지금 방식(손글씨 폰트 + 무작위 변형)은 데이터와 GPU 없이 돌아가고, 인쇄해서 봤을 때 손글씨로 보이는 수준이다. 다만 글씨체는 폰트 7종 안에서만 고를 수 있다.
- "내 글씨체를 몇 글자만 써서 흉내 내기"는 폰트 생성 모델로 할 수 있어 보이지만, 공개된 한글 모델은 낯선 필체에서 품질이 불안정하다고 스스로 밝히고 있다. 바로 붙일 만한 것은 못 찾았다.
- 가장 현실적인 다음 단계는 **모델이 만든 글자 이미지를 폰트처럼 써서 지금 렌더러에 넣는 것**이다. 렌더러는 글리프 윤곽선만 받으면 되므로(`fonts.py` 의 `GlyphOutline`), 글자 이미지를 윤곽선으로 바꾸는 단계만 더하면 된다.

## 한글 글씨체 생성 모델

| 모델 | 하는 일 | 확인한 것 | 확인 못 한 것 |
|---|---|---|---|
| [MX-Font++ Korean (HERIUN)](https://huggingface.co/HERIUN/mxfontpp-korean-handwriting) | 참고 글자 이미지 몇 장의 필체로 한글 글자를 생성. 인쇄체와 나눔손글씨로 학습 | 모델 카드가 "필자별, 학습 범위 밖 필체는 신뢰할 수 없다"고 적고 있음. 문장이 아니라 글자 단위 출력 | 가중치 라이선스, 실제 품질 |
| [MX-Font (clovaai)](https://awesome.ecosyste.ms/projects/github.com%2Fclovaai%2Fmxfont) | 몇 글자로 폰트 생성(ICCV 2021). 중국어로 학습해 한글로 옮기는 실험 포함 | 코드는 MIT(단 `modules.py` 는 NVlabs/FUNIT 에서 가져온 것). 학습에 쓴 폰트는 라이선스 문제로 공개 안 함 | 공개 가중치의 라이선스와 한글 품질 |
| [FontDiffuser](https://arxiv.org/abs/2312.12142v1) | 한 글자만 보고 폰트 생성(확산 모델, AAAI 2024). 중국어 → 한글 교차 생성 시연 | 논문과 [코드 저장소](https://github.com/yeungchenwa/FontDiffuser) 존재 | 라이선스, 가중치 공개 여부, 한글 품질 |
| [GAN-handwriting-styler](https://github.com/jeina7/GAN-handwriting-styler) | 일부 글자만 학습하고 나머지 한글을 생성하는 GAN | 저장소 존재 | 라이선스, 유지 여부 |

공통된 한계: 모두 **글자 한 자씩** 만든다. 글자 사이 흐름이나 줄 단위 흔들림은 없으므로 그 부분은 지금 렌더러가 계속 맡아야 한다.

## 한글 손글씨 데이터

- [AI Hub](https://aihub.or.kr/web-nas/aihub21/files/sample/intro/Q&A%20%EC%82%AC%EB%A1%80%EC%A7%91%20%EC%B5%9C%EC%A2%85-%EB%82%B1%EC%9E%A5.pdf) 에 2019년 구축된 "한국어 글자체 이미지" 데이터가 있다(**확인함**: 존재).
  이용 조건(신청 자격, 상업 이용, 재배포)은 검색으로 **확인 못 함**. 데이터 상세 페이지의 이용약관과 사용신청서를 직접 봐야 한다.
  어떤 조건이든 이 저장소는 공개 저장소이므로 **데이터 파일은 올리지 않는다**(`.gitignore` 의 `datasets/`).
- 펜 움직임(획 순서, 속도)까지 담긴 공개 한글 데이터는 찾지 못했다. 영어의 Graves 식 모델을 한글로 옮기기 어려운 이유다.
  스마트펜으로 1,500줄을 직접 써서 학습했다는 [발표](https://seoul.aitinkerers.org/meetup/mu_S59ghBQyAzM/recap)는 있으나 코드 공개는 **확인 못 함**.

## 영어를 먼저 할 경우

- [sjvasquez/handwriting-synthesis](https://www.github.com/sjvasquez/handwriting-synthesis/issues/58): 획 순서까지 생성하는 Graves 식 모델이라 결과가 매우 자연스럽다.
  그러나 **저장소에 라이선스 파일이 없다**(확인함). 라이선스가 없으면 원칙적으로 가져다 쓸 권리가 없다.
- 학습 데이터인 [IAM On-Line](https://fki.tic.heia-fr.ch/databases/download-the-iam-on-line-handwriting-database)은 **비상업 연구용**으로만 쓸 수 있다(확인함).
  기업용 카드 제작은 상업 이용이므로 이 데이터로 학습한 모델을 그 용도에 쓰는 것은 권하지 않는다.
- 그래서 영어도 지금 방식(영문 손글씨 폰트 + 변형)으로 먼저 지원하는 편이 안전하다. 지금 렌더러는 폰트에 영문 글리프가 있으면 그대로 쓴다.

## 문장 생성 API (NVIDIA NIM)

- 엔드포인트 `https://integrate.api.nvidia.com/v1`, 모델 `meta/llama-3.3-70b-instruct` 는 여러 자료에서 같은 이름으로 확인된다([모델 페이지](https://build.nvidia.com/meta/llama-3_3-70b-instruct)).
- 무료 사용 한도는 NVIDIA가 고정된 숫자로 공개하지 않는다. 분당 30~40회라는 [제3자 분석](https://news.creeta.com/ko/nvidia-nim-free-tier-limits-2026-ko/)이 있으나 **확인 못 함**. 정확한 값은 build.nvidia.com 계정 화면에서 봐야 한다.
- 모델이 예고 없이 내려가는 일이 있다는 보고가 있어, 모델 이름은 코드가 아니라 `.env`(`SON_LLM_MODEL`)로 바꿀 수 있게 했다.

## 다음에 해 볼 순서

1. 사용자가 직접 쓴 글자 20~50자를 사진으로 받아 윤곽선으로 바꾸고, 없는 글자만 기존 폰트로 채우는 "내 글씨 섞어 쓰기". 모델 없이 가능하다.
2. MX-Font++ Korean 을 Colab 에서 돌려 실제 품질 확인. 쓸 만하면 1번의 빈 글자를 모델 출력으로 채운다. 가중치 라이선스를 먼저 확인한다.
3. 한글 획 데이터를 직접 모으는 것은 그다음 일이다.
