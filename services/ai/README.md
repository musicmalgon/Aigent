# Re:Mind AI

> 새 `분노/기쁨/불안/당황/슬픔/무기력` 실험은
> [`docs/emotion_taxonomy_v2_training_guide.md`](docs/emotion_taxonomy_v2_training_guide.md)를
> 따른다. 선정된 v2 모델은 별도 `/v2/emotions/classify` 계약으로 제공하며
> 기존 coarse-v1 공유 계약과 저장 이력은 변경하지 않는다.
> 현재 모델의 confidence/margin abstention 품질과 threshold grid 평가는
> [`docs/emotion_abstention_evaluation.md`](docs/emotion_abstention_evaluation.md)를
> 따른다.

> The six-class coarse-emotion runtime and API are documented in
> [`docs/coarse_emotion_inference.md`](docs/coarse_emotion_inference.md). The
> existing four-label `EmotionAnalysis` contract remains supported.
>
> Six-class training, dry-run, and artifact packaging are documented in
> [`docs/transformer_coarse_baseline_guide.md`](docs/transformer_coarse_baseline_guide.md).

Re:Mind AI 파트는 초기 자가 보고 결과를 고정 기준점으로 보관하면서 개인별
생활 변화와 감정 일기 분석 결과를 결합할 수 있는 데이터 계약과 분석
인터페이스를 담당합니다. 이 모듈은 의료적 판단이나 진단을 제공하지 않습니다.

## 1차 기반 구축 범위

이번 단계에서 제공하는 항목은 다음과 같습니다.

- Assessment / Behavioral / Emotion / Pattern / Combined Signal Pydantic 모델
  및 JSON Schema
- `stable`, `fatigue`, `anxiety`, `other` 감정 라벨 명세와 원본 라벨 매핑
  초안
- TF-IDF와 Transformer 감정 분석기의 공통 인터페이스 및 미준비 상태 오류
- profile-safe split을 그대로 재사용하는 KLUE-RoBERTa 학습 baseline과 dry-run
- 모델명·모델 버전을 명시적으로 요구하고 미평가 관련성은 `null`로 보존하는
  추론 계약
- 가중합을 사용하지 않는 신호 결합 규칙의 보수적인 뼈대와 Reason Code
- 합성 일기 평가셋 초안과 합성 생활 시나리오 데이터
- Assessment 정책, Behavioral Baseline 명세, 백엔드 전달 초안
- 스키마, 인터페이스, 합성 데이터를 검증하는 테스트

실제 AI Hub 데이터와 모델 가중치, Behavioral Baseline 계산 알고리즘, 확정 임계값,
LLM 설명 생성, 백엔드 API는 포함하지 않습니다. 검증된 coarse Transformer 실험
결과와 재현 절차는 `docs/transformer_coarse_baseline_guide.md`에 기록합니다.

## 디렉터리 구조

```text
services/ai/
├── data/
│   ├── evaluation/       # 사람이 검토할 합성 외부 평가셋 초안
│   ├── processed/        # 로컬 전처리 데이터(커밋 금지)
│   ├── raw/              # 로컬 원본 데이터(커밋 금지)
│   └── synthetic/        # 합성 생활 시나리오
├── config/               # 검토 가능한 라벨 매핑
├── docs/                 # 실행·평가·연동 가이드
├── scripts/              # 로컬 학습 진입점
├── src/
│   ├── emotion/          # 감정 분석 공통 인터페이스와 구현 뼈대
│   ├── signal/           # Reason Code와 신호 결합 뼈대
│   └── schemas.py        # Pydantic 데이터 모델
└── tests/
```

## 환경과 테스트

Python 3.11 이상을 기준으로 합니다. 현재 저장소 경로의 `:`는 `PATH`
구분자이므로, 이 환경의 `venv` 모듈은 해당 문자가 포함된 저장소 내부 대상
경로 생성을 거부합니다. 권장 가상환경은 저장소 밖의
`$HOME/.venvs/remind-ai`에 만들고 개발 의존성을 설치합니다. 공식 테스트
명령은 저장소 루트에서 실행합니다.

```bash
cd /path/to/Aigent
python3 -m venv "$HOME/.venvs/remind-ai"
source "$HOME/.venvs/remind-ai/bin/activate"
python -m pip install -r services/ai/requirements-dev.txt
export PYTHONPATH=services
python -m pytest -q
python -m ruff check services/ai/src services/ai/tests services/ai/scripts
python -m mypy services/ai/src
python -m compileall -q services/ai/src services/ai/tests
python -c "import ai.src.signal; import ai.src.schemas"
```

대안은 저장소를 `rewind` 또는 `re-wind`처럼 `:` 없는 경로에서 사용하는
것입니다. 이번 기반 구축 작업에서는 기존 저장소를 이동하거나 이름을 바꾸지
않았습니다.

공식 Python 패키지 경로는 `ai.src`입니다. 저장소 루트에서
`PYTHONPATH=services`를 설정하면 학습 스크립트, 백엔드 연동, 테스트가 같은 import
경로를 사용합니다.

`requirements.txt`는 Pydantic과 TF-IDF 추론 의존성을,
`requirements-dev.txt`는 테스트·정적 검사 도구를 포함합니다. Transformer
구현을 실제로 연결하는 단계에서만 CPU 추론용 선택 의존성을 설치합니다.

```bash
python -m pip install -r services/ai/requirements-transformer.txt
```

GPU 가속 환경은 운영 플랫폼과 드라이버에 맞는 PyTorch 설치 방법을 별도로
확정해야 하며, 이 초기 requirements 파일이 GPU 환경을 보장하지는 않습니다.

## 감정 분석기 연결 계약

- 두 분석기는 `EmotionAnalyzer.predict(text) -> EmotionAnalysis`를
  공통으로 사용합니다.
- 생성할 때 `model_name`과 `model_version`을 명시해야 합니다.
- 현재 감정 분류기 뼈대는 원인 및 수면·업무 관련성을 계산하지 않습니다.
  따라서 `cause_tags=[]`, `sleep_related=null`, `workload_related=null`을
  반환합니다. `null`은 미평가이며 `false`와 다릅니다.
- 로컬 아티팩트가 없거나 로드되지 않았거나 의존성이 불완전하면 공통
  `EmotionAnalyzerError` 계층의 구체적인 예외를 발생시킵니다.
- Transformer 로더는 로컬 디렉터리만 받고 `local_files_only=True`로
  자동 다운로드를 차단합니다.
- 모델 경로는 서버의 신뢰된 설정에서만 지정하고 API 요청이나 사용자 입력으로
  받지 않습니다.

TF-IDF의 joblib 파일은 pickle 기반이므로 로드하는 것만으로 임의 코드가
실행될 수 있습니다. 팀이 직접 생성하고 출처·해시·Python/scikit-learn/joblib
버전을 확인한 아티팩트만 사용해야 합니다. 사용자 업로드나 출처가 불명확한
파일을 `load()`에 전달하지 않습니다.

## 향후 TF-IDF 학습 순서

1. 사용 조건을 확인한 원본 데이터와 확정된 라벨을 준비합니다.
2. 원본 라벨 매핑표를 사람이 검토하고 버전을 고정합니다.
3. 학습/검증/외부 평가 데이터의 중복과 누수를 점검합니다.
4. 동일한 전처리 규칙으로 vectorizer와 classifier를 학습합니다.
5. 검토된 평가 기준으로 모델을 평가하고 모델 카드를 작성합니다.
6. Python, scikit-learn, joblib 버전과 아티팩트 해시를 manifest에 남깁니다.
7. 검증한 두 아티팩트를 로컬 모델 경로에 저장하고 명시적인 모델명·버전으로
   `TfidfEmotionAnalyzer`에 연결합니다.

## Transformer baseline 로컬 실행 순서

1. 모델과 데이터의 라이선스·사용 조건을 확인합니다.
2. 확정된 감정 라벨과 데이터 분할을 재사용합니다.
3. 60-class는 `docs/transformer_baseline_guide.md`, 6-class는
   `docs/transformer_coarse_baseline_guide.md`의 dry-run을 먼저 수행합니다.
4. 선택 의존성 환경에서 별도의 학습 실험을 수행합니다.
5. 외부 평가셋과 오류 사례를 사람이 검토합니다.
6. 배포 후보의 버전과 라벨 매핑을 고정한 뒤 공통 `EmotionAnalysis`
   출력으로 어댑터를 연결합니다.

## 데이터 및 표현 안전

- 실제 사용자 개인정보, 건강 데이터, 원본 학습 데이터, 모델 가중치는
  커밋하지 않습니다.
- 이 저장소의 CSV는 모두 개발용 합성 데이터이며 사람의 검토 전에는 모델
  학습 데이터로 사용하지 않습니다.
- 초기 자가 보고 결과는 AI가 수정하거나 재계산하지 않는 고정 기준점입니다.
- 누락값은 `null` 또는 `coverage="unavailable"`로 표현하며 측정값 `0`과
  구분합니다.
- 결과는 생활 패턴 신호 설명에 한정하며 의료적 진단·확률·치료 판단으로
  해석하지 않습니다.

## Recovery Report 문장화

`POST /v1/recovery-reports/generate`는 백엔드가 계산한 최근 7일 facts와
미리 선택한 recovery action만 받아 한국어 문장을 구조화된 JSON으로
반환합니다. 원문 일기는 받지 않으며, 수치 재계산·원인 추정·새 행동 추천·
의료 표현을 금지합니다.

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash
GEMINI_TIMEOUT_SECONDS=20
REPORT_PROMPT_VERSION=recovery-report-prompt-v1
```

API key가 없거나 Gemini 호출·JSON 검증이 실패하면 AI endpoint는 오류를
반환합니다. Backend Recovery Report API는 이 오류를 사용자에게 전파하지
않고 규칙 기반 템플릿으로 완성된 리포트를 저장합니다.
