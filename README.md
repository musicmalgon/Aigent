# Re:Mind (Aigent)

Re:Mind는 사용자의 평소 생활 리듬과 최근 기록을 비교하고, 한국어 감정 분석과
설명 가능한 규칙 기반 위험 신호를 결합해 부담이 낮은 회복 행동을 제안하는
비진단적 자기관리 서비스입니다.

이 저장소는 AI 모델 학습·추론, 생활 기록 및 개인 기준선, 번아웃 Risk Engine,
회복 리포트, 백엔드 API, Web 및 Android 클라이언트를 포함하는 모노레포입니다.

> Re:Mind의 결과는 의료 진단, 질병 확률, 치료 또는 처방이 아닙니다. 모델 성능과
> Risk Engine의 정책값도 임상적 타당성을 의미하지 않습니다.

## 핵심 처리 흐름

```text
Health Connect 또는 직접 기록
  └─ 수면 · 걸음 · 운동 · 휴식 · 업무/학업 · 일정 수
       └─ Behavioral Daily Record
            ├─ 14~28일 개인 기준선(Behavioral Baseline)
            └─ 현재 기록과 기준선 비교

감정 일기
  └─ KLUE-RoBERTa 6분류 + 불확실성/Neutral Gate
       └─ 감정 확률 · confidence · margin · provenance

생활 변화 + 감정 결과 + 주관적 피로
  └─ Explainable Burnout Risk Engine
       └─ 점수 · 단계 · 데이터 품질 · Reason Code
            └─ 회복 행동 후보 선정
                 └─ Gemini 제한형 문장화 또는 규칙 기반 fallback
```

LLM은 위험 점수를 계산하거나 변경하지 않습니다. 위험도는 버전이 고정된
결정론적 Risk Engine에서 계산하며, Gemini는 백엔드가 확정한 사실과 허용된 행동을
한국어 문장으로 정리하는 역할만 담당합니다.

## 직접 구현한 핵심 범위

아래 범위는 Git 작성자 `edgar-1019`, `edgar1019522`, `10.19.hh`의 구현 이력을
기준으로 정리했습니다. 팀 전체 기능과 개인 구현 범위가 섞이지 않도록 데이터
수집 클라이언트와 화면 구현은 별도로 구분합니다.

### 1. AI 데이터·학습 기반

- Assessment, Behavioral, Emotion, Pattern, Combined Signal의 Pydantic 모델과
  JSON Schema 설계
- AI Hub 데이터 구조, 라벨 품질, 중복 및 누수를 검사하는 로컬 감사 도구 구현
- 사용자 프로필, 대화, 정규화 문장 중복을 분리하는 leakage-safe split 구현
- TF-IDF 감정 분류 baseline과 학습·평가·아티팩트 저장 파이프라인 구현
- KLUE-RoBERTa 기반 Transformer 감정 분류 학습 파이프라인 구현
- 세부 감정을 6개 대분류로 변환하는 라벨 정책 및 매핑 검증 구현
- 학습 진행률, checkpoint, 재시작, 평가 지표 및 재현 메타데이터 기록

### 2. 감정 추론과 불확실성 처리

- 6개 감정(`분노`, `기쁨`, `불안`, `당황`, `슬픔`, `무기력`) 추론 API 구현
- 모델·토크나이저·라벨 순서·학습 설정을 시작 시 검증하는 아티팩트 로더 구현
- confidence와 top-1/top-2 margin 기준을 모두 통과해야 제품 감정으로 채택하는
  abstention 정책 구현
- 감정 표현이 없는 문장을 먼저 걸러내는 Neutral Gate 학습·평가·추론 파이프라인
  구현
- 모델 버전, taxonomy, threshold 버전, 불확실성 및 처리 단계를 추적하는
  provenance 계약 구현
- 원문을 로그나 DB에 저장하지 않고 로컬 모델 아티팩트만 로드하도록 제한

선정된 6분류 실험 아티팩트의 저장된 internal test 결과는 accuracy `0.6781`,
macro-F1 `0.6891`입니다. 이는 동결된 연구 실험의 내부 결과이며 실제 사용자 성능,
API SLO 또는 임상 성능을 의미하지 않습니다.

### 3. 생활 기록과 개인 기준선

- 수면, 걸음, 활동, 운동, 업무·학업, 휴식, 일정 수, 주관적 피로를 저장하는
  일별 생활 기록 계약·API·영속성 구현
- 필드별 출처와 수집 상태를 함께 저장하여 실제 `0`과 미연동 `null`을 구분
- 기본 14일, 선택 14~28일 범위에서 사용자별 Behavioral Baseline 계산
- 지표마다 사용 가능한 날짜만 평균에 반영하고 최소 7일 이상일 때 `ready` 판정
- 기준선과 Risk 평가를 버전 및 입력 provenance와 함께 append-only로 저장

Health Connect에서 수면·걸음·운동을 읽는 Android 수집 코드는 팀원이 구현했습니다.
직접 구현 범위는 수집된 데이터의 공통 계약, 검증, 저장, 개인 기준선 계산 및 Risk
Engine 연결입니다.

### 4. Explainable Burnout Risk Engine

`burnout-risk-rules-v1`은 현재 관측값을 개인 기준선과 비교해 `0~100` 점수와
감사 가능한 원인 목록을 반환하는 결정론적 정책 엔진입니다.

| 범주 | 주요 입력 | 기본 가중치 |
| --- | --- | ---: |
| 수면 | 기준선 대비 수면 감소 | 0.25 |
| 업무 부담 | 업무·학업 시간 증가, 일정 수 증가 | 0.20 |
| 회복 | 휴식 및 운동 감소 | 0.20 |
| 감정 | 부정 감정 확률 변화와 모델 신뢰도 | 0.20 |
| 주관 지표 | 스트레스 및 피로 증가 | 0.15 |

주요 구현 특성:

- 수면·휴식·운동 감소와 업무량·일정 증가를 개인 기준선 대비 변화량으로 계산
- 일정 수 증가를 `SCHEDULE_OVERLOAD`, 업무·학업 시간 증가를
  `WORKLOAD_INCREASE` Reason Code로 기록
- 감정 top label 하나가 아니라 6개 감정의 전체 확률 분포를 사용
- 감정 confidence와 uncertainty를 반영해 신뢰도가 낮은 신호의 영향 축소
- 누락 범주를 정상이나 `0`으로 간주하지 않고 사용 가능한 범주의 가중치를 재조정
- 기준선 또는 데이터가 부족한 결과는 `provisional`로 표시하고 점수 상한 적용
- 점수에 기여한 관측값, 기준값, 변화량, severity, weight, contribution을 함께 반환
- 동일 입력을 다시 평가해도 과거 평가를 덮어쓰지 않는 감사 이력 유지

### 5. Stage 2 멀티라벨 신호

기존 단일 감정 분류와 별도로 한 입력에서 다음 신호를 동시에 탐지하는 sigmoid
멀티라벨 학습·추론 경로를 구현했습니다.

- 에너지 소진(`exhaustion`)
- 과부하(`overload`)
- 통제하기 어려운 느낌(`helplessness`)
- 해낸 느낌 저하(`low_efficacy`)
- 불안(`anxiety`)
- 예민함(`irritability`)

라벨별 검증 상태와 임계값을 독립적으로 적용하며, 결과는 `present`, `absent`,
`unvalidated`로 구분합니다. 현재 전체 모델은 `shadow_only`이며 위험점수에는
사용하지 않습니다. 검증된 활성 신호만 회복 행동의 보조 순위에 제한적으로 사용할
수 있고, 모든 응답은 `informational_only=true`, `risk_score_eligible=false`입니다.

### 6. 제한형 회복 리포트와 행동 추천

- 최근 7일의 확정된 facts와 사전 정의된 회복 행동만 받는 Gemini 리포트 API 구현
- Structured Output과 Pydantic 검증으로 응답 JSON 구조 고정
- 수치 재계산, 원인 추정, 새로운 행동 생성, 의료 표현을 프롬프트와 후처리에서 차단
- Risk Engine의 factor와 선택 가능한 행동 catalog를 연결하는 결정론적 추천 정책 구현
- Gemini가 허용된 후보 중 1~3개 ID만 선택하도록 제한하고 서버에서 재검증
- API key 누락, timeout, 잘못된 JSON 또는 금지 표현 발생 시 규칙 기반 템플릿으로
  안전하게 fallback
- 행동 선택, 완료 및 리포트 생성 provenance를 영속화하고 API로 제공

기본 Gemini 모델은 `gemini-3.1-flash-lite`이며 환경변수로 명시적으로 설정합니다.

## 팀 연동 기능과 현재 제한

| 기능 | 현재 상태 | 구현 구분 |
| --- | --- | --- |
| Android Health Connect | 수면·걸음·운동 세션 읽기 및 백그라운드 동기화 코드 구현 | 팀원 구현 |
| 건강 데이터 저장·기준선·분석 | 공통 계약, API, DB, 기준선, Risk Engine 연결 완료 | 직접 구현 |
| 일정 기반 상태 분석 | `schedule_count`를 개인 평균과 비교해 일정 과부하 계산 | 직접 구현 |
| Google Calendar 자동 연동 | UI 안내와 데이터 필드만 존재, 실제 OAuth/동기화 미구현 | 미구현 |
| Web 화면 | 기록·리포트·계획 API 연동 및 데모 화면 | 팀 구현 |
| Stage 2 전체 자동 판정 | 전체 라벨 검증 전이므로 shadow 전용 | 연구 진행 중 |

따라서 현재 일정 기능은 캘린더 서비스에서 일정을 자동 수집하는 “일정 관리”가
아니라, 입력된 `schedule_count`의 변화를 Risk Engine이 분석하는 기능입니다.

## 저장소 구조

```text
Aigent/
├─ apps/mobile/                   # Android, Health Connect 동기화
├─ packages/contracts/            # 서비스 간 공유 JSON Schema
├─ services/ai/                   # 학습, 감정/Stage 2 추론, Gemini 문장화
├─ services/backend/              # API, DB, 기준선, Risk Engine, 회복 정책
├─ services/frontend/User dashboard/
│                                  # 사용자 Web 화면
└─ docker-compose.yml
```

## 주요 API

### AI service (`:8001`)

| Method | Endpoint | 설명 |
| --- | --- | --- |
| `GET` | `/health/live` | 프로세스 상태 |
| `GET` | `/health/ready` | 모델 및 아티팩트 준비 상태 |
| `POST` | `/v2/emotions/classify` | 6분류 감정 및 불확실성 추론 |
| `POST` | `/v1/burnout-signals/analyze` | Stage 2 멀티라벨 shadow 분석 |
| `POST` | `/v1/recovery-reports/generate` | 제한형 회복 리포트 문장화 |
| `POST` | `/v1/recovery-actions/select` | 허용된 후보 내 회복 행동 선택 |

### Backend (`:8000`)

- `/api/v1/behavioral-records`: 생활 기록 생성·조회·수정·삭제
- `/api/v1/baselines`: 개인 기준선 계산 및 조회
- `/api/v1/emotion-analyses`: 감정 일기 분석 orchestration
- `/api/v1/risk-evaluations`: Risk Engine 실행 및 이력 조회
- `/api/v1/recovery-reports`: 회복 리포트 생성 및 조회
- `/api/v1/recovery-plans`: 추천 행동 조회, 선택 및 완료
- `/api/v1/readiness`: 사용자의 데이터 준비 상태

## 로컬 실행

### Docker Compose

각 서비스의 `.env.example`을 `.env`로 복사하고 모델 아티팩트를 준비한 뒤 실행합니다.

```bash
docker compose up --build
```

- Frontend: `http://localhost:3000`
- Backend/OpenAPI: `http://localhost:8000/docs`
- AI service는 Compose 내부 `8001` 포트에서 Backend와 통신합니다.

모델 가중치와 학습 출력은 런타임 아티팩트이므로 저장소에 커밋하지 않습니다.
자세한 모델 배치는
[`services/ai/docs/coarse_emotion_inference.md`](services/ai/docs/coarse_emotion_inference.md)를
참고합니다.

### 서비스별 개발 환경

Python `3.12`를 기준으로 Backend와 AI 환경을 분리하는 것을 권장합니다.

```powershell
# Backend
cd services\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

```powershell
# AI service: 저장소 루트에서 실행
py -3.12 -m venv .venv-ai
.\.venv-ai\Scripts\Activate.ps1
python -m pip install -r services\ai\requirements-dev.txt
python -m pip install -r services\ai\requirements-transformer.txt
$env:PYTHONPATH = "services"
python -m uvicorn ai.src.main:app --host 127.0.0.1 --port 8001
```

운영 환경에서는 `JWT_SECRET_KEY`, `GEMINI_API_KEY`와 같은 비밀값을 저장소나
`.env.example`에 기록하지 말고 별도 secret manager로 관리해야 합니다.

## 검증

```powershell
# 저장소 루트
$env:PYTHONPATH = "services;services/backend"
python -m pytest -q -p no:cacheprovider
python -m ruff check .
python -m mypy services/backend
python -m compileall -q services/ai/src services/backend/app
```

실제 모델 smoke test와 unit test는 구분합니다. unit/API test는 synthetic text와
fake model component를 사용하며 원본 사용자 데이터나 동결된 internal test split을
반복 평가하지 않습니다.

## 안전 및 개인정보 원칙

- 원문 감정 일기는 AI 요청에만 사용하고 DB, 응답, 애플리케이션 로그에 저장하지 않음
- 건강 데이터 미연동과 실제 측정값 `0`을 구분
- 모델 아티팩트는 신뢰된 로컬 경로에서만 로드
- Risk Engine과 모델·threshold·prompt 버전을 결과 provenance에 기록
- LLM이 위험 점수, 관측 수치, 원인 또는 허용 행동을 변경하지 못하도록 검증
- Stage 2 결과를 의료 판단이나 기존 위험점수에 사용하지 않음
- 건강·감정 데이터를 별도 동의 없이 모델 재학습이나 분석에 재사용하지 않음

## 상세 문서

- [AI 서비스 개요](services/ai/README.md)
- [6분류 감정 추론](services/ai/docs/coarse_emotion_inference.md)
- [감정 abstention 평가](services/ai/docs/emotion_abstention_evaluation.md)
- [Stage 2 연동 정책](services/ai/docs/stage2_burnout_signal_integration.md)
- [Risk Engine v1](services/backend/docs/burnout_risk_engine_v1.md)
- [생활 기록·기준선 영속성](services/backend/docs/behavioral_persistence.md)
- [Risk Evaluation API](services/backend/docs/risk_evaluation_api.md)
- [Recovery Report API](services/backend/docs/recovery_report_api.md)
