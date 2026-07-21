Re:Mind 프로젝트에서 AI 파트의 1차 개발 기반을 구축해 주세요.

이 프로젝트는 대상별 초기 자가 보고 결과를 고정 기준점으로 저장하고,
생활·건강 데이터의 개인별 변화와 감정 일기 분석 결과를 결합하여
생활 패턴 위험 신호와 주요 원인을 제공하는 서비스입니다.

이번 작업에서는 모델 학습이나 백엔드 API 구현까지 진행하지 말고,
AI 파트의 명세, 데이터 구조, 테스트 데이터, 추론 인터페이스를 먼저 완성해 주세요.

────────────────────────────────────────
1. 이번 작업의 목표
────────────────────────────────────────

이번 작업이 끝나면 다음이 가능해야 합니다.

1. 백엔드가 AI 입력·출력 구조를 기준으로 DB와 API를 설계할 수 있어야 합니다.
2. 감정 데이터의 원본 라벨을 Re:Mind의 감정 라벨로 매핑할 기준이 있어야 합니다.
3. TF-IDF 모델과 Transformer 모델이 같은 인터페이스를 사용하도록 뼈대가 준비되어야 합니다.
4. 합성 생활 데이터로 향후 멀티시그널 규칙을 테스트할 수 있어야 합니다.
5. K-BAT 확인 결과와 무관하게 개발이 멈추지 않는 fallback 정책이 문서화되어야 합니다.
6. 생성된 문서·스키마·데이터에 대한 기본 검증 테스트가 실행되어야 합니다.

────────────────────────────────────────
2. 먼저 프로젝트 구조 확인
────────────────────────────────────────

작업 전에 현재 저장소를 확인하세요.

- 기존 Python 환경과 패키지 관리 방식을 확인하세요.
- pyproject.toml, requirements.txt, uv.lock, poetry.lock 등이 있는지 확인하세요.
- 기존 backend, frontend, ai 디렉터리가 있는지 확인하세요.
- 기존 구조를 깨거나 중복 환경을 만들지 마세요.
- 프로젝트에 이미 Pydantic이 있다면 기존 버전에 맞추세요.
- AI 관련 디렉터리가 없다면 아래 구조를 생성하세요.

ai/
├─ README.md
├─ data/
│  ├─ raw/
│  │  └─ .gitkeep
│  ├─ processed/
│  │  └─ .gitkeep
│  ├─ evaluation/
│  │  └─ remind_diary_eval.csv
│  └─ synthetic/
│     └─ synthetic_daily_records.csv
├─ docs/
│  ├─ emotion_label_spec.md
│  ├─ emotion_label_map.csv
│  ├─ assessment_policy.md
│  ├─ behavioral_baseline_spec.md
│  ├─ scenario_definitions.md
│  ├─ backend_handoff_draft.md
│  └─ schemas/
│     ├─ assessment_anchor.schema.json
│     ├─ behavioral_daily_record.schema.json
│     ├─ behavioral_baseline.schema.json
│     ├─ emotion_analysis.schema.json
│     ├─ pattern_change.schema.json
│     └─ combined_signal_result.schema.json
├─ src/
│  ├─ __init__.py
│  ├─ schemas.py
│  ├─ emotion/
│  │  ├─ __init__.py
│  │  ├─ base.py
│  │  ├─ tfidf_analyzer.py
│  │  └─ transformer_analyzer.py
│  └─ signal/
│     ├─ __init__.py
│     ├─ reason_codes.py
│     └─ combine_signals.py
└─ tests/
   ├─ test_schemas.py
   ├─ test_emotion_interface.py
   └─ test_synthetic_data.py

원본 학습 데이터, 모델 가중치, 개인정보가 Git에 포함되지 않도록
필요하다면 .gitignore도 수정하세요.

────────────────────────────────────────
3. 감정 라벨 명세 작성
────────────────────────────────────────

ai/docs/emotion_label_spec.md를 작성하세요.

Re:Mind의 1차 감정 라벨은 다음 4개입니다.

- stable: 안정
- fatigue: 피로
- anxiety: 불안
- other: 기타

각 라벨에 대해 다음 내용을 작성하세요.

- 정의
- 포함되는 표현
- 포함되지 않는 표현
- 경계 사례
- 다른 라벨과 충돌할 때의 우선 판단 기준
- 멀티 감정 문장의 처리 원칙
- confidence가 낮을 때의 처리 원칙

기본 기준은 다음과 같습니다.

stable:
편안함, 만족, 평온, 긍정적 상태 또는 특별한 부정 신호가 없는 상태

fatigue:
지침, 무기력, 에너지 부족, 회복되지 않음, 아무것도 하기 싫음

anxiety:
긴장, 걱정, 초조, 압박, 두려움, 불확실성에 대한 불안

other:
슬픔, 분노, 혼합 감정, 문맥 부족, 현재 분류 체계로 판단하기 어려운 상태

주의사항:

- 번아웃, 우울증, 불안장애 등의 의료적 진단 라벨을 만들지 마세요.
- 하나의 문장에 불안과 피로가 함께 있을 수 있으므로
  primary_emotion과 secondary_signals를 분리할 수 있게 설계하세요.
- other가 지나치게 큰 클래스가 될 수 있다는 한계를 문서에 적으세요.

────────────────────────────────────────
4. 원본 라벨 매핑표 작성
────────────────────────────────────────

ai/docs/emotion_label_map.csv를 작성하세요.

컬럼:

original_label,remind_label,reason,review_status,notes

초기 예시 행을 작성하되,
실제 AI Hub 데이터에 존재한다고 확인하지 않은 라벨을
확정된 사실처럼 작성하지 마세요.

예시:

기쁨,stable,긍정적인 정서,draft,실제 원본 라벨 확인 필요
편안,stable,안정적인 상태,draft,실제 원본 라벨 확인 필요
피로,fatigue,직접 대응,draft,실제 원본 라벨 확인 필요
무기력,fatigue,에너지 저하,draft,실제 원본 라벨 확인 필요
불안,anxiety,직접 대응,draft,실제 원본 라벨 확인 필요
걱정,anxiety,유사 정서,draft,실제 원본 라벨 확인 필요
분노,other,현재 핵심 분류 외,draft,세부 분류 확장 가능
슬픔,other,현재 핵심 분류 외,draft,세부 분류 확장 가능

실제 데이터가 들어오면 매핑을 검토해야 한다는 TODO를 남기세요.

────────────────────────────────────────
5. Assessment 정책 작성
────────────────────────────────────────

ai/docs/assessment_policy.md를 작성하세요.

다음 정책을 명확하게 포함하세요.

대학생:
- 이번 MVP에서는 자체 초기 생활 상태 설문을 사용합니다.
- 자체 설문은 표준화된 심리검사가 아닙니다.
- 의료적 진단이나 번아웃 확정에 사용하지 않습니다.
- 출력 차원 예시는 exhaustion, academic_burden, recovery_difficulty입니다.
- 실제 문항과 해석 문구는 팀 검토가 필요합니다.

사회초년생:
- K-BAT 사용 조건과 결과 표시 기준을 확인 중입니다.
- 문의 결과는 개발을 블로킹하지 않습니다.
- 1주차 종료 시점까지 사용 조건을 확인하지 못하면
  사회초년생도 자체 초기 상태 설문으로 진행합니다.
- 이후 허용 범위가 확인되면 교체할 수 있도록
  assessment_type으로 분리합니다.

공통:
- 초기 설문 결과는 Assessment Anchor로 저장합니다.
- AI가 설문 점수를 수정하거나 재계산하지 않습니다.
- Assessment Anchor는 최종 진단값이나 정답 라벨이 아닙니다.
- 생활·감정 변화 해석을 돕는 고정 기준점으로만 사용합니다.
- “진단”, “확정”, “치료 필요” 등의 표현을 사용하지 않습니다.

────────────────────────────────────────
6. JSON Schema 및 Pydantic 모델 작성
────────────────────────────────────────

다음 6개 JSON Schema 파일과 대응하는 Pydantic 모델을 작성하세요.

1. AssessmentAnchor
2. BehavioralDailyRecord
3. BehavioralBaseline
4. EmotionAnalysis
5. PatternChangeResult
6. CombinedSignalResult

Pydantic 모델은 ai/src/schemas.py에 작성하세요.

권장 필드는 다음과 같습니다.

AssessmentAnchor:
- assessment_type
- target_group
- completed_at
- dimensions
- interpretation_scope
- source

BehavioralDailyRecord:
- user_id
- date
- sleep_minutes
- bedtime
- wake_time
- steps
- active_minutes
- exercise_minutes
- work_or_study_minutes
- rest_minutes
- schedule_count
- subjective_fatigue
- source_by_field
- coverage_by_field

BehavioralBaseline:
- baseline_start
- baseline_end
- valid_days
- minimum_required_days
- data_sufficiency
- averages
- medians
- weekday_averages
- weekend_averages

EmotionAnalysis:
- primary_emotion
- secondary_signals
- confidence
- cause_tags
- sleep_related
- workload_related
- model_name
- model_version

PatternChangeResult:
- data_sufficiency
- change_level
- duration_days
- factors
- calculation_version

CombinedSignalResult:
- combined_level
- result_type
- reason_codes
- top_factors
- missing_signals
- assessment_summary
- behavior_summary
- emotion_summary
- rule_version

다음 원칙을 지키세요.

- Enum 또는 Literal을 사용해 가능한 값을 제한하세요.
- nullable과 실제 숫자 0을 구분하세요.
- 건강 데이터가 없으면 null과 coverage="unavailable"을 사용하세요.
- 임의의 진단 확률 필드는 만들지 마세요.
- Pydantic 모델과 JSON Schema의 필드가 일치해야 합니다.
- 각 스키마에 valid example을 포함하세요.

────────────────────────────────────────
7. 감정 분석 공통 인터페이스 작성
────────────────────────────────────────

ai/src/emotion/base.py에 공통 인터페이스를 작성하세요.

다음과 같은 형태를 권장합니다.

from abc import ABC, abstractmethod

class EmotionAnalyzer(ABC):
    @abstractmethod
    def predict(self, text: str) -> EmotionAnalysis:
        ...

TF-IDF와 Transformer 구현체가 동일한 EmotionAnalysis를 반환해야 합니다.

ai/src/emotion/tfidf_analyzer.py:
- 아직 실제 학습은 진행하지 않습니다.
- 모델 로딩 경로, predict 인터페이스, 미학습 상태 오류 처리를 구현하세요.
- joblib 기반으로 모델과 vectorizer를 로드할 수 있게 설계하세요.
- 실제 모델 파일이 없을 때 명확한 예외를 발생시키세요.

ai/src/emotion/transformer_analyzer.py:
- 아직 모델 다운로드나 파인튜닝을 하지 않습니다.
- 동일한 predict 인터페이스를 구현할 수 있는 뼈대만 작성하세요.
- Transformers 의존성이 현재 프로젝트에 없다면 강제로 추가하지 마세요.
- 선택 의존성으로 처리하고, 설치되지 않았을 때 명확한 오류를 반환하세요.

────────────────────────────────────────
8. Reason Code와 신호 결합 뼈대 작성
────────────────────────────────────────

ai/src/signal/reason_codes.py에 최소 다음 Reason Code를 정의하세요.

- ASSESSMENT_EXHAUSTION_ELEVATED
- BEHAVIOR_DATA_INSUFFICIENT
- HEALTH_DATA_NOT_CONNECTED
- SLEEP_DECREASE_CONTINUED
- ACTIVITY_DECREASE_CONTINUED
- REST_DECREASE_CONTINUED
- FATIGUE_EXPRESSION_REPEATED
- ANXIETY_EXPRESSION_REPEATED
- EMOTION_DATA_MISSING
- NEW_PATTERN_CHANGE
- MULTIPLE_SIGNALS_ALIGNED
- SELF_REPORT_ELEVATED_WITHOUT_RECENT_CHANGE

ai/src/signal/combine_signals.py에는 완전한 위험도 알고리즘을 아직 구현하지 말고,
입력·출력 타입과 기본 규칙 뼈대를 작성하세요.

다음 상태를 처리할 수 있어야 합니다.

- 모든 신호가 안정
- 초기 설문은 높지만 생활·감정은 안정
- 초기 설문은 낮지만 생활·감정이 악화
- 세 신호가 모두 악화
- 생활 데이터 부족
- 건강 데이터 연동 거부
- 감정 일기 미작성

임의의 40%, 30% 같은 가중합은 사용하지 마세요.

────────────────────────────────────────
9. 일기체 평가셋 초안 작성
────────────────────────────────────────

ai/data/evaluation/remind_diary_eval.csv를 작성하세요.

이번 1차 작업에서는 30문장만 생성하세요.

컬럼:

id,text,primary_emotion,secondary_signals,cause_tags,review_status,review_note

조건:

- stable, fatigue, anxiety, other가 과도하게 불균형하지 않도록 구성하세요.
- 대학생, 취업 준비생, 사회초년생 상황을 섞으세요.
- 시험, 팀 프로젝트, 아르바이트, 면접, 야근, 수면 부족, 평범한 하루,
  회복되는 날 등의 상황을 포함하세요.
- 실제 사용자 데이터가 아닌 합성 문장임을 명시하세요.
- 모든 행의 review_status를 "needs_human_review"로 설정하세요.
- 모델 학습 데이터로 바로 사용하지 말고 외부 평가셋 초안으로 취급하세요.
- 의료적 위기 문장을 임의로 대량 생성하지 마세요.

────────────────────────────────────────
10. 합성 생활 데이터 작성
────────────────────────────────────────

ai/data/synthetic/synthetic_daily_records.csv를 작성하세요.

1주차에는 다음 3개 시나리오만 만드세요.

1. stable_user
   - 생활 패턴이 비교적 안정적
   - 14일 이상 유효 기록

2. worsening_user
   - 앞 기간은 안정적
   - 최근 7일 수면·활동·휴식이 감소
   - 감정 일기는 fatigue 또는 anxiety 경향

3. insufficient_user
   - 유효 기록이 부족하여 Baseline 생성 불가

컬럼:

user_id,date,sleep_minutes,steps,active_minutes,exercise_minutes,
work_or_study_minutes,rest_minutes,schedule_count,subjective_fatigue,
sleep_source,steps_source,coverage

조건:

- 실제 사용자 데이터가 아닌 합성 데이터여야 합니다.
- stable_user와 worsening_user는 최소 14일 이상 작성하세요.
- insufficient_user는 데이터 부족 상태가 명확해야 합니다.
- 비현실적인 수치가 없도록 기본 범위를 검증하세요.
- 시나리오 설명은 ai/docs/scenario_definitions.md에 작성하세요.

다음 두 시나리오는 이번 작업에서 만들지 말고 TODO로 남기세요.

- 설문 결과가 높지만 최근 생활은 안정적인 사용자
- 설문 결과는 낮지만 최근 생활·감정이 악화된 사용자

이 두 시나리오는 3주차 신호 결합 테스트에서 추가할 예정입니다.

────────────────────────────────────────
11. Behavioral Baseline 명세 초안
────────────────────────────────────────

ai/docs/behavioral_baseline_spec.md를 작성하세요.

이번에는 코드 구현이 아니라 명세 초안까지만 작성합니다.

반드시 포함할 내용:

- 최소 Baseline 후보 기간: 14일
- 최근 비교 후보 기간: 7일
- 유효 기록 일수 정의
- 평균과 중앙값 비교 필요성
- 평일·주말 분리 여부
- 수면·걸음 수·활동 시간·휴식 시간 변화량
- 데이터 부족 조건
- 건강 데이터 미연동 처리
- 자동 데이터와 수동 입력이 충돌할 때의 처리 후보
- 하루만 변한 경우와 며칠 지속된 경우의 구분
- 모든 임계값은 의료 기준이 아니라 MVP 실험 규칙이라는 안내

확정되지 않은 임계값은 임의로 확정하지 말고
“초기 후보” 또는 TODO로 표시하세요.

────────────────────────────────────────
12. 테스트 작성
────────────────────────────────────────

다음 테스트를 작성하고 실행하세요.

test_schemas.py:
- 각 Pydantic 모델의 정상 생성
- 잘못된 Enum 값 거부
- null과 0 구분
- JSON Schema example 검증

test_emotion_interface.py:
- TF-IDF와 Transformer 구현체가 동일 인터페이스를 가지는지 확인
- 모델 미설치·미학습 상태의 오류가 명확한지 확인

test_synthetic_data.py:
- 필수 컬럼 존재
- 날짜 형식 검증
- 수면 시간이 0~1440분 범위인지 확인
- 걸음 수와 활동 시간이 음수가 아닌지 확인
- stable/worsening/insufficient 시나리오가 모두 존재하는지 확인
- 원본 사용자 정보가 없는 합성 데이터인지 확인 가능한 메타데이터 검증

프로젝트에 기존 테스트 명령이 있으면 그것을 사용하세요.
없다면 AI 디렉터리에서 실행 가능한 최소 pytest 구성을 만드세요.

────────────────────────────────────────
13. README 및 백엔드 전달 초안
────────────────────────────────────────

ai/README.md에 다음 내용을 작성하세요.

- AI 파트의 책임 범위
- 이번 1차 작업에서 구현한 것
- 아직 구현하지 않은 것
- 디렉터리 구조
- 테스트 실행 방법
- 향후 TF-IDF 학습 순서
- 향후 Transformer 파인튜닝 순서
- 개인정보와 의료적 표현 관련 주의사항

ai/docs/backend_handoff_draft.md에는 다음을 작성하세요.

- 백엔드가 저장해야 하는 AI 관련 데이터
- AI 모듈의 입력·출력 모델
- 필드 단위와 nullable 의미
- 건강 데이터가 없을 때의 처리
- 감정 분석 모델 교체가 API에 영향을 주지 않는 구조
- 향후 전달 예정 함수:
  - analyze_diary(text)
  - build_baseline(records)
  - compare_recent_pattern(baseline, recent_records)
  - combine_signals(assessment, behavior, emotion)
- 현재는 초안이며 알고리즘 임계값은 확정 전이라는 안내

────────────────────────────────────────
14. 작업 금지 사항
────────────────────────────────────────

이번 작업에서는 다음을 하지 마세요.

- AI Hub 데이터를 임의로 다운로드하지 마세요.
- 실제 K-BAT 문항을 출처 확인 없이 복사하지 마세요.
- K-BAT 사용 가능 여부를 추정해서 확정하지 마세요.
- 의료적 진단 알고리즘을 만들지 마세요.
- 번아웃 확률을 출력하지 마세요.
- Health Connect·HealthKit 코드를 구현하지 마세요.
- 백엔드 DB나 인증 코드를 수정하지 마세요.
- 프론트엔드 디자인을 변경하지 마세요.
- Transformer 모델을 다운로드하거나 파인튜닝하지 마세요.
- 실제 사용자 데이터를 생성하거나 포함하지 마세요.
- 실제 모델 성능 수치를 만들어내지 마세요.
- 존재하지 않는 라이선스 조건을 사실처럼 작성하지 마세요.

────────────────────────────────────────
15. 완료 보고 형식
────────────────────────────────────────

작업 완료 후 다음 형식으로 보고하세요.

1. 생성하거나 수정한 파일 목록
2. 각 파일의 역할
3. 백엔드에 즉시 전달 가능한 스키마
4. 사람이 반드시 검토해야 하는 항목
5. 아직 미확정인 정책과 TODO
6. 실행한 테스트 명령
7. 테스트 결과
8. 현재 막혀 있는 외부 의존성
9. 다음 작업으로 권장하는 순서

다음 작업은 이번 실행에서 자동으로 시작하지 마세요.

- AI Hub 실제 데이터 전처리
- TF-IDF 학습
- Transformer 파인튜닝
- Behavioral Baseline 알고리즘 구현
- LLM 프롬프트 구현

이번 실행은 1주차 초반에 필요한 기반 구축까지만 완료하세요.
기존 저장소 구조와 코딩 스타일을 최대한 유지하고,
불필요하게 대규모 리팩터링하지 마세요.