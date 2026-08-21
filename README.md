# Re:Mind

> 생활 리듬과 감정 변화를 함께 살펴보고, 설명 가능한 위험 신호를 바탕으로 작은
> 회복 행동을 제안하는 비진단적 자기관리 서비스

Re:Mind는 수면·활동·운동·휴식·업무·일정 같은 생활 데이터와 감정 일기를
기록하고, 사용자의 평소 생활 패턴과 최근 상태를 비교합니다. 한국어 감정 분석과
규칙 기반 Risk Engine이 변화 원인을 설명하며, 결과에 맞는 낮은 강도의 회복 행동을
제안합니다.

이 프로젝트의 결과는 의료 진단, 질병 확률, 치료 또는 처방이 아닙니다. 모델 성능과
Risk Engine의 정책값 역시 임상적 타당성을 의미하지 않습니다.

## 주요 기능

### 생활·건강 데이터 기록

- 수면 시간과 취침·기상 시각
- 걸음 수, 활동 시간, 운동 시간
- 업무·학업 시간, 휴식 시간, 하루 일정 수
- 주관적 피로와 감정 일기
- 필드별 데이터 출처와 수집 상태 관리
- Android Health Connect 수면·걸음·운동 데이터 동기화

실제 측정값 `0`과 데이터 미연동 상태를 구분합니다. 건강 데이터가 없다는 이유로
사용자의 활동을 `0`으로 간주하지 않습니다.

### 개인 생활 기준선

- 기본 14일, 선택 가능한 14~28일 기록으로 Behavioral Baseline 계산
- 지표별로 값이 존재하는 날짜만 평균에 반영
- 최소 7일 이상 기록이 모이면 `ready`, 그보다 적으면 `insufficient`로 구분
- 기준선의 계산 기간, 알고리즘 버전과 데이터 provenance 저장

### 한국어 감정 분석

- KLUE-RoBERTa 기반 6개 감정 분류
  - 분노, 기쁨, 불안, 당황, 슬픔, 무기력
- confidence와 top-1/top-2 margin을 함께 사용하는 불확실성 판정
- 감정 표현이 없는 문장을 먼저 식별하는 Neutral Gate
- 모델, taxonomy, threshold 버전을 포함한 추론 provenance
- 원문 일기를 DB와 애플리케이션 로그에 저장하지 않는 처리 정책

선정된 6분류 실험 아티팩트의 저장된 internal test 결과는 accuracy `0.6781`,
macro-F1 `0.6891`입니다. 이는 동결된 내부 연구 결과이며 실제 사용자 성능이나
임상 성능을 의미하지 않습니다.

### Explainable Burnout Risk Engine

현재 기록을 개인 기준선과 비교하여 `0~100`의 제품 위험 신호와 원인 목록을
계산합니다. LLM이 점수를 계산하거나 변경하지 않으며, 모든 판정은 버전이 고정된
결정론적 규칙으로 수행됩니다.

| 범주 | 분석 항목 | 기본 가중치 |
| --- | --- | ---: |
| 수면 | 개인 기준선 대비 수면 감소 | 0.25 |
| 업무 부담 | 업무·학업 시간 및 일정 수 증가 | 0.20 |
| 회복 | 휴식 및 운동 감소 | 0.20 |
| 감정 | 부정 감정 확률 변화와 모델 신뢰도 | 0.20 |
| 주관 지표 | 스트레스 및 피로 증가 | 0.15 |

- 일정 수 증가를 `SCHEDULE_OVERLOAD`, 업무·학업 시간 증가를
  `WORKLOAD_INCREASE`로 기록
- 일부 데이터가 없으면 사용 가능한 범주의 가중치만 재조정
- 기준선 또는 데이터가 부족한 결과는 `provisional`로 표시하고 점수 상한 적용
- 관측값, 기준값, 변화량, severity, weight, contribution을 Reason Code와 함께 반환
- 동일 입력의 재평가도 과거 결과를 덮어쓰지 않고 감사 이력으로 보존

### Stage 2 멀티라벨 신호

기존 감정 분류와 별도로 한 일기에서 다음 신호가 함께 나타나는지 분석하는 연구
경로를 제공합니다.

- 에너지 소진(`exhaustion`)
- 과부하(`overload`)
- 통제하기 어려운 느낌(`helplessness`)
- 해낸 느낌 저하(`low_efficacy`)
- 불안(`anxiety`)
- 예민함(`irritability`)

라벨별 검증 상태와 threshold를 독립적으로 적용하여 `present`, `absent`,
`unvalidated`로 구분합니다. 현재 전체 모델은 `shadow_only`이며 Risk Engine 점수에
사용하지 않습니다. 모든 결과는 `informational_only=true`,
`risk_score_eligible=false`입니다.

### 회복 리포트와 행동 계획

- Risk Engine이 확정한 최근 7일의 변화 요인으로 회복 리포트 생성
- 수면, 휴식, 운동, 업무와 일정 부담에 대응하는 낮은 강도의 행동 catalog 제공
- 사용자가 추천 행동을 선택하고 완료 상태를 기록
- Gemini Structured Output을 활용한 한국어 리포트 문장화
- 수치 재계산, 원인 추정, 의료 표현 및 catalog 밖 행동 생성을 차단
- Gemini 호출 실패 시 규칙 기반 템플릿으로 안전하게 fallback

Gemini는 서버가 허용한 사실과 행동만 문장으로 정리합니다. 위험도 계산과 행동 후보
구성은 Backend의 결정론적 정책이 담당합니다.

### Web 및 Android

- 이메일/비밀번호 및 Google OAuth 로그인
- 초기 자가 보고, 생활 기록, 감정 일기 작성
- 대시보드, 과거 기록, 위험 리포트와 회복 계획 화면
- 데이터 활용 동의 등록·조회·철회 및 사용자 데이터 삭제
- Android WebView 기반 서비스 화면
- Health Connect 권한 관리와 WorkManager 기반 백그라운드 동기화

## 서비스 처리 흐름

```text
┌──────────────────────┐     ┌─────────────────────────┐
│ Android Health       │     │ Web / 직접 생활 기록    │
│ Connect              │     │ 감정 일기               │
└──────────┬───────────┘     └────────────┬────────────┘
           └──────────────┬───────────────┘
                          ▼
              ┌───────────────────────────┐
              │ FastAPI Backend           │
              │ 인증 · 동의 · API · DB    │
              └───────┬───────────┬───────┘
                      │           │
        생활 기록/기준선           │ 감정 일기
                      ▼           ▼
              ┌─────────────┐  ┌──────────────────────┐
              │ Risk Engine │  │ AI Service           │
              │ 규칙 기반   │◀─│ 감정/Stage 2 추론    │
              └──────┬──────┘  └──────────────────────┘
                     ▼
              ┌───────────────────────────┐
              │ Recovery Report / Plan    │
              │ 정책 추천 + Gemini 문장화│
              └───────────────────────────┘
```

## 최초 사용자 플로우

웹 로그인과 모바일 네이티브 로그인은 서로 다른 세션입니다(SSO 미연동). 모바일
네이티브 로그인은 Health Connect 동기화 권한 용도로만 쓰이고, 실제 기록/조회는
웹(또는 앱 안의 WebView)에서 이뤄집니다.

### 웹 회원가입

1. 이메일/비밀번호 또는 Google OAuth로 회원가입
2. 동의 화면에서 5개 항목 확인
   - 필수: 서비스 이용약관, 개인정보 수집 및 이용, 건강·생활 데이터 활용, 생활
     흐름 분석 활용
   - 선택: 외부 서비스 연동
   - 필수 4개를 모두 체크해야 다음 단계로 진행 가능
3. 초기 자가 보고 설문 → 홈 화면

### 모바일 Health Connect 동기화

1. 앱 설치 후 네이티브 로그인 화면에서 로그인
2. 홈 화면의 "지금 동기화"를 누르면 Health Connect 권한 요청 다이얼로그 표시
   (수면·걸음·심박·운동 데이터 읽기 권한)
3. 권한을 허용하면 즉시 동기화되어 서버에 저장됨 — 이때 건강·생활 데이터 활용
   동의가 아직 없으면 동기화 로직이 자동으로 동의를 등록한 뒤 진행
4. 웹(또는 WebView)의 "오늘 기록" 화면에서 "건강데이터 가져오기"로 동기화된
   값을 불러와 확인·수정 가능

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| Web | React, TypeScript, Vite, Tailwind CSS, MUI, Recharts |
| Android | Kotlin, Jetpack Compose, WebView, Health Connect, WorkManager, Retrofit |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic |
| AI/ML | PyTorch, Transformers, KLUE-RoBERTa, scikit-learn |
| LLM | Gemini Structured Output |
| Database | SQLite(로컬·테스트), PostgreSQL 배포 고려 |
| Infra | Docker Compose |
| Test/Quality | pytest, Ruff, mypy, Android JUnit |

## 모노레포 구조

```text
Aigent/
├─ apps/mobile/                       # Android 및 Health Connect 동기화
├─ packages/contracts/                # 서비스 간 공유 JSON Schema
├─ services/
│  ├─ ai/                             # 학습, 감정/Stage 2 추론, LLM 문장화
│  ├─ backend/                        # API, DB, 기준선, Risk Engine, 회복 정책
│  └─ frontend/User dashboard/        # React 사용자 화면
├─ docker-compose.yml
└─ README.md
```

모델 가중치, tokenizer, 원본 학습 데이터와 생성된 학습 결과는 런타임 또는 로컬
아티팩트이며 저장소에 커밋하지 않습니다.

## 주요 API

### Backend (`:8000`)

| 영역 | Endpoint |
| --- | --- |
| 인증 | `/auth/signup`, `/auth/login`, `/auth/google/*` |
| 사용자 | `/users/me`, `/users/me/data` |
| 동의 | `/api/v1/consents` |
| 초기 평가 | `/assessments/anchor` |
| 생활 기록 | `/api/v1/behavioral-records` |
| 개인 기준선 | `/api/v1/baselines` |
| 감정 분석 | `/api/v1/emotion-analyses` |
| 위험 평가 | `/api/v1/risk-evaluations` |
| 회복 리포트 | `/api/v1/recovery-reports` |
| 회복 계획 | `/api/v1/recovery-plans` |
| 대시보드/준비도 | `/api/v1/dashboard`, `/api/v1/readiness` |

### AI service (`:8001`)

| Method | Endpoint | 설명 |
| --- | --- | --- |
| `GET` | `/health/live` | 프로세스 상태 |
| `GET` | `/health/ready` | 모델과 아티팩트 준비 상태 |
| `POST` | `/v2/emotions/classify` | 6분류 감정 및 불확실성 추론 |
| `POST` | `/v1/burnout-signals/analyze` | Stage 2 멀티라벨 shadow 분석 |
| `POST` | `/v1/recovery-reports/generate` | 제한형 회복 리포트 문장화 |
| `POST` | `/v1/recovery-actions/select` | 허용된 후보 내 회복 행동 선택 |

## 시작하기

### 요구 사항

- Docker Desktop 및 Docker Compose, 또는
- Python `3.12`, Node.js, Android Studio
- 감정 추론 사용 시 별도로 준비한 모델 아티팩트
- LLM 문장화 사용 시 Gemini API key

### Docker Compose

Backend와 AI 서비스의 환경 파일을 먼저 준비합니다.

```bash
cp services/backend/.env.example services/backend/.env
cp services/ai/.env.example services/ai/.env
docker compose up --build
```

Windows PowerShell:

```powershell
Copy-Item services\backend\.env.example services\backend\.env
Copy-Item services\ai\.env.example services\ai\.env
docker compose up --build
```

- Web: `http://localhost:3000`
- Backend Swagger UI: `http://localhost:8000/docs`
- AI service는 Compose 내부의 `8001` 포트에서 Backend와 통신합니다.

`docker-compose.yml`의 모델 volume 경로에 감정 모델과 Neutral Gate 아티팩트를
읽기 전용으로 배치해야 AI readiness가 통과합니다.

### Backend 단독 실행

```powershell
cd services\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

개발 기본 DB는 `sqlite:///./remind.db`입니다. 테스트는 별도의 임시 SQLite DB만
사용합니다.

### AI service 단독 실행

저장소 루트에서 실행합니다.

```powershell
py -3.12 -m venv .venv-ai
.\.venv-ai\Scripts\Activate.ps1
python -m pip install -r services\ai\requirements-dev.txt
python -m pip install -r services\ai\requirements-transformer.txt
$env:PYTHONPATH = "services"
python -m uvicorn ai.src.main:app --host 127.0.0.1 --port 8001
```

주요 환경변수는 `EMOTION_ARTIFACT_DIR`, `EMOTION_DEVICE`,
`EMOTION_CONFIDENCE_THRESHOLD`, `EMOTION_MARGIN_THRESHOLD`,
`BURNOUT_SIGNALS_ENABLED`, `GEMINI_API_KEY`, `GEMINI_MODEL`입니다.

### Web 단독 실행

```powershell
cd "services\frontend\User dashboard"
npm install
$env:VITE_API_BASE_URL = "http://localhost:8000"
npm run dev
```

### Android

Android Studio에서 `apps/mobile`을 열어 실행합니다. Health Connect 데이터 읽기에는
지원 기기, Health Connect provider와 사용자의 명시적 권한 승인이 필요합니다.

## 테스트 및 품질 검사

### Python 전체

```powershell
$env:PYTHONPATH = "services;services/backend"
python -m pytest -q -p no:cacheprovider
python -m ruff check .
python -m mypy services/backend
python -m compileall -q services/ai/src services/backend/app
```

### Web

```powershell
cd "services\frontend\User dashboard"
npm run build
```

### Android

```powershell
cd apps\mobile
.\gradlew.bat test
```

실제 모델 smoke test와 unit test는 구분합니다. unit/API test는 합성 텍스트와 fake
model component를 사용하며, 원본 사용자 데이터나 동결된 internal test split을
반복 평가하지 않습니다.

## 개인정보 및 안전 원칙

- 건강·감정 데이터 사용 전에 목적별 동의를 확인
- 원문 감정 일기를 DB, 응답 또는 애플리케이션 로그에 저장하지 않음
- 사용자 삭제 시 소유 데이터의 연쇄 삭제를 지원
- 건강 데이터 미연동과 관측된 `0`을 명확히 구분
- 신뢰된 로컬 경로의 모델 아티팩트만 로드
- 모델, threshold, Risk Engine과 prompt 버전을 결과에 기록
- LLM이 위험 점수, 관측 수치, 원인 또는 허용 행동을 변경하지 못하도록 검증
- Stage 2 결과를 의료 판단이나 기존 Risk Engine 점수에 사용하지 않음
- 별도 동의 없이 건강·감정 데이터를 모델 재학습에 사용하지 않음

## 현재 제한 사항

- Google Calendar 자동 연동은 아직 구현되지 않았습니다. 현재는 입력된
  `schedule_count`를 개인 기준선과 비교해 일정 과부하를 분석합니다.
- Stage 2 여섯 라벨 전체는 독립 검증이 완료되지 않아 shadow mode로만 동작합니다.
- 감정 모델 결과는 내부 실험 결과이며 실제 환경 calibration과 공정성 검토가
  추가로 필요합니다.
- Risk Engine의 가중치와 구간은 설명 가능한 제품 정책 가설이며 임상 기준이
  아닙니다.
- 일부 홈·초기 설문 화면에는 시연용 표현 또는 로컬 상태가 남아 있을 수 있습니다.

## 상세 문서

- [AI 서비스 개요](services/ai/README.md)
- [6분류 감정 추론](services/ai/docs/coarse_emotion_inference.md)
- [감정 abstention 평가](services/ai/docs/emotion_abstention_evaluation.md)
- [Stage 2 연동 정책](services/ai/docs/stage2_burnout_signal_integration.md)
- [Backend 실행 및 운영](services/backend/README.md)
- [생활 기록·기준선 영속성](services/backend/docs/behavioral_persistence.md)
- [Risk Engine v1](services/backend/docs/burnout_risk_engine_v1.md)
- [Risk Evaluation API](services/backend/docs/risk_evaluation_api.md)
- [Recovery Report API](services/backend/docs/recovery_report_api.md)

## License

현재 저장소에는 별도의 공개 라이선스가 명시되어 있지 않습니다. 코드와 데이터의
사용·배포 전 저장소 소유자 및 각 외부 데이터·모델의 이용 조건을 확인하세요.
