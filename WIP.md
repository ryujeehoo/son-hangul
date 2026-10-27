# 작업 중 (2026-10-27 기준, 11월 중순 재개 예정)

미완성 상태다. 아직 한 번도 실행해 보지 않았다. 요구사항 전체는 `docs/project-brief.md`.

## 된 것
- `pyproject.toml`, `.env.example`, `sonhangul/config.py`: NVIDIA NIM 설정(lecture-summarizer 방식 그대로)
- `sonhangul/fonts.py`: Google Fonts(OFL) 한글 손글씨 폰트 7종 목록, 자동 내려받기,
  글리프 윤곽선 → 점 목록, 폰트별 크기 정규화('가' 높이 기준), 없는 글자 대체 폰트
  - Gaegu 는 2,350자만 있어서 대체 폰트가 필요함(확인함)
- `sonhangul/noise.py`: 값 노이즈 / 프랙탈 노이즈
- `sonhangul/render.py`: 줄바꿈, 글자·획·줄·전체 단위 무작위 변형, 감김수 규칙 래스터화

## 남은 것
1. `sonhangul/ink.py`: `Pen` 프리셋(볼펜, 젤펜, 만년필, 연필, 사인펜),
   `shape_glyph`(굵기·필압·윤곽 거칠기, 고해상도에서), `apply_tone`(농도, 볼펜 끊김, 연필 결, 번짐, 테두리 진함)
   — render.py 가 이미 이 이름들로 import 하고 있음
2. `paper.py`(무지/줄/모눈/크라프트/낡은 종이), `export.py`(PNG·투명 PNG·노멀맵·PDF 카드/A4)
3. `compose.py`(NVIDIA API 문장 생성, 캐시, 재시도, 오프라인 템플릿), `batch.py`(CSV → messages.csv → PDF)
4. `cli.py`(`handwrite render|compose|batch|fonts`), `webui.py`(Gradio)
5. 테스트, 샘플 이미지 눈으로 보며 흔들림 정도 튜닝, README
6. 2단계: AI 손글씨 모델 조사 → `docs/research.md`
   (참고: HERIUN/MXFontpp-korean, clovaai dmfont/lffont/mxfont, FontDiffuser,
   영어는 sjvasquez/handwriting-synthesis)

## 비슷한 서비스 조사 메모
- Handwrytten(미국): ChatGPT 문구 + 로봇 펜 실물 발송. 한글 지원은 확인 못 함.
- 국내 크몽 손편지 대행: 사람이 직접, 200자 5천 원 안팎.
- 한글 문장 → 사람 같은 손글씨 이미지를 만드는 무료 도구는 찾지 못함.
