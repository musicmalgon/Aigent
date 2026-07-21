# 백엔드 전달 초안

## 상태와 계약 원칙

- 상태: 1차 개발 계약 초안
- 기준 모델: `services/ai/src/schemas.py`와 `packages/contracts/schemas/*.schema.json`
- 현재 알고리즘 임계값과 판정 규칙: 확정 전

백엔드는 초기 자가 보고 원본, 생활 기록 원본, 감정 분석 결과, Re:Mind의
패턴 변화 결과를 서로 구분해 저장해야 한다. 이 문서는 DB 테이블 구조를
강제하지 않으며 API와 저장 계층이 잃지 않아야 할 의미를 정의한다.

## 저장해야 하는 AI 관련 데이터

### Assessment

- `AssessmentAnchor` 원본
- 평가 유형, 대상 그룹, 완료 시각, 설문·버전 출처
- 원본이 제공한 차원별 값과 해석 범위
- 정정 또는 교체가 있다면 덮어쓰기 대신 추적 가능한 버전 정보

AI는 Assessment Anchor 점수를 수정하거나 재계산하지 않는다. 자체 설문과
향후 사용 조건이 확인될 수 있는 평가를 `assessment_type`으로 구분한다.

### Behavior

- 수집된 `BehavioralDailyRecord` 원본
- 각 지표의 값, 출처, 커버리지
- 사용자 날짜와 현지 시각을 계산한 `time_zone` IANA 식별자
- 중복·정정·삭제 이력을 추적할 식별 정보
- 계산된 `BehavioralBaseline`, 전체 유효 일수, 지표별 유효 일수·충분도와
  계산 버전
- 최근 비교 결과인 `PatternChangeResult`와 사용한 기간

원본 레코드와 계산 결과를 별도로 저장해 재계산할 수 있어야 한다.

### Emotion

- 분석 입력을 참조할 수 있는 일기 식별자와 작성 시각
- `EmotionAnalysis`
- 모델명과 모델 버전
- 입력 원문 보관 여부, 보관 기간, 삭제 정책은 개인정보 검토 후 확정

분석 결과만으로 원문을 복원할 수 있다고 가정하지 않는다. 원문을
저장하지 않는 설계를 선택할 경우 재분석 제약을 명시해야 한다.

### Combined result

- `CombinedSignalResult`
- 참조한 Assessment Anchor, 행동 비교 결과, 감정 분석 결과의 버전
- 규칙 버전과 생성 시각
- 이유 코드, 주요 요인, 누락 신호

## AI 입력·출력 모델

| 처리 단계 | 입력 | 출력 | 현재 상태 |
|---|---|---|---|
| 감정 분석 | 일기 텍스트 | `EmotionAnalysis` | 공통 인터페이스와 미학습 뼈대 |
| Baseline 생성 | `BehavioralDailyRecord[]` | `BehavioralBaseline` | 향후 구현 |
| 최근 패턴 비교 | `BehavioralBaseline`, 최근 `BehavioralDailyRecord[]` | `PatternChangeResult` | 향후 구현 |
| 신호 결합 | 정책이 해석한 `AssessmentSignal`, `BehaviorSignal`, `EmotionSignal` | `CombinedSignalResult` | 기본 규칙 뼈대 |

요청·응답 직렬화는 Pydantic 모델과 JSON Schema의 필드명, 타입, enum을
따른다. 백엔드 구현 전 두 표현이 일치하는지 테스트 결과를 확인한다.
JSON Schema Draft 2020-12만으로는 두 인스턴스 숫자의 대소 관계나 두 날짜의
순서를 동적으로 비교할 수 없다. 따라서 JSON Schema 통과만으로 입력이
완전히 유효하다고 간주하지 말고 Pydantic 모델 또는 동등한 교차 필드
검증기를 반드시 함께 실행한다.

현재 신호 결합 뼈대는 Assessment 원본 점수나 생활 변화 임계값을 직접
계산하지 않는다. 각 소유 정책이 원본과 계산 버전을 보존한 채 해석한
상태만 `AssessmentSignal`, `BehaviorSignal`, `EmotionSignal`로 전달한다.
향후 오케스트레이션 계층은 이 상태 요약과 원본 `AssessmentAnchor`,
`PatternChangeResult`, `EmotionAnalysis`의 참조를 함께 추적해야 한다.

`BehavioralBaseline.valid_days`는 기간 안에 하나 이상의 행동 값이 있었던
날짜 수다. `valid_days_by_metric`과 `sufficiency_by_metric`은 같은 지표
키를 사용해 지표마다 서로 다른 커버리지를 보존한다. 지표 키는
`BaselineMetric`으로 제한된다. 지표별 충분도는 다음 의미를 사용한다.

- `sufficient`: 해당 지표를 분석할 수 있다고 버전별 정책이 판단함
- `partial`: 값은 있으나 안정적인 비교에는 부족함
- `insufficient`: 버전별 분석 기준에 미달함
- `unavailable`: 해당 지표의 유효 값이 없으며 유효 일수는 `0`

지표별 최소 유효 일수는 아직 확정하지 않은 `TODO`다. 전체
`minimum_required_days`를 모든 지표에 임의로 적용하지 않는다.
`BehavioralBaseline.calculation_version`은 필수이며, 집계 정책이 바뀌면
기존 결과에 새 의미를 덮어쓰지 않고 새 버전으로 계산한다.

`PatternChangeResult`는 데이터가 충분하지 않으면
`change_level=unknown`, `duration_days=null`, 빈 `factors`만 허용한다.
충분한 데이터에서 `no_notable_change`는 관찰된 변화 지속일이 없다는 뜻의
`duration_days=0`과 빈 `factors`를 사용한다. `change_observed`는 양수
지속일과 하나 이상의 factor가 필요하다.

## 필드 단위와 nullable 의미

| 필드 | 단위·형식 | `null` 의미 | 숫자 `0` 의미 |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | 허용하지 않음 | 해당 없음 |
| `time_zone` | 날짜 산출에 사용한 IANA 식별자 | 허용하지 않음 | 해당 없음 |
| `completed_at` | 시간대가 있는 ISO 8601 일시 | 허용하지 않음 | 해당 없음 |
| `sleep_minutes` | 분, `0..1440` | 값 없음 | 관측된 수면 0분 |
| `active_minutes` | 분, 0 이상 | 값 없음 | 관측된 활동 0분 |
| `exercise_minutes` | 분, 0 이상 | 값 없음 | 관측된 운동 0분 |
| `work_or_study_minutes` | 분, 0 이상 | 값 없음 | 관측된 일·학업 0분 |
| `rest_minutes` | 분, 0 이상 | 값 없음 | 관측된 휴식 0분 |
| `steps` | 걸음 수, 0 이상 | 값 없음 | 관측된 0걸음 |
| `schedule_count` | 일정 수, 0 이상 | 값 없음 | 관측된 일정 0개 |
| `subjective_fatigue` | 비음수 자가 보고 값 | 미작성 | 척도에서 0이 정의된 경우의 응답 |
| `bedtime`, `wake_time` | 현지 시각 | 값 없음 | 해당 없음 |
| `sleep_related`, `workload_related` | 감정 분석 관련성 | 해당 관계를 분석하지 않음 | 해당 없음 |

`subjective_fatigue`의 실제 척도 상한과 0의 허용 의미는 설문 정책 확정 전
`TODO`다. 합성 CSV의 1~5 예시를 운영 계약으로 간주하지 않는다.

`time_zone`은 사용자 프로필의 현재값을 조회해 과거 레코드에 덮어쓰지
않는다. 이동 또는 DST가 있어도 각 레코드의 `date`, `bedtime`,
`wake_time`을 산출할 때 사용한 식별자를 함께 보존한다. 현재 정규식은 IANA
형태만 제한하므로, 백엔드는 런타임의 시간대 데이터베이스에 존재하는
식별자인지도 입력 경계에서 확인해야 한다.

`source_by_field`와 `coverage_by_field`는 지표별로 저장한다. 하나의 행에
수면은 있고 걸음 수는 없을 수 있으므로 행 단위 플래그만으로 대체하지
않는다.

`sleep_related=false`와 `workload_related=false`는 실제 관계 분석을
수행한 뒤 관련성이 없다고 판단한 경우에만 사용한다. 현재 TF-IDF와
Transformer 뼈대는 관계 추출기를 포함하지 않으므로 두 필드를 모두
`null`로 반환한다.

## 건강 데이터가 없을 때

- 해당 값은 `null`로, 커버리지는 `unavailable`로 전달한다.
- 데이터 없음, 연동하지 않음, 수집 오류를 숫자 `0`으로 바꾸지 않는다.
- 출처를 제공하지 못하는 경우 스키마가 허용하는 `not_provided`를
  사용한다.
- 연동하지 않은 상태를 결합 결과에 반영할 때는
  `HEALTH_DATA_NOT_CONNECTED` 또는 누락 신호를 사용하고 생활 악화로
  간주하지 않는다.
- 일부 지표만 있으면 지표별 가용성을 유지하고 없는 지표의 변화량을
  생성하지 않는다.

연동하지 않음과 기술적 오류를 API에서 별도 사유 코드로 구분할지는
백엔드 오류 계약과 함께 검토한다.

## 감정 모델 교체에 독립적인 API

TF-IDF와 Transformer 구현체는 같은 `EmotionAnalyzer.predict(text)` 계약과
`EmotionAnalysis` 출력을 사용한다.

- API 응답은 모델 전용 내부 점수나 토크나이저 결과를 노출하지 않는다.
- `primary_emotion`, `secondary_signals`, `confidence`, `cause_tags`,
  관련 플래그를 공통 필드로 전달한다.
- `model_name`과 `model_version`으로 결과 재현과 비교가 가능해야 한다.
- 분석기 생성 시 `model_name`과 `model_version`을 명시해야 하며 실제
  결과에 암묵적인 `unversioned` 값을 사용하지 않는다.
- confidence는 모델의 출력 확신도이며 생활·건강 상태의 확률이 아니다.
- 모델별 confidence가 같은 척도라고 가정하지 않는다.
- 모델 교체로 공통 필드 의미가 바뀌면 API를 조용히 변경하지 않고 스키마
  또는 분석 버전을 올린다.

TF-IDF joblib 아티팩트는 팀이 생성하고 검증한 내부 파일만 로드한다.
사용자 업로드 파일을 직접 역직렬화하지 않으며 모델 경로는 사용자 입력이
아닌 서버 설정으로 지정한다. 배포 단계에서는 Python·scikit-learn·joblib
버전과 파일 checksum을 담은 manifest 검증을 추가하는 것이 `TODO`다.

## 향후 전달 예정 함수

```python
analyze_diary(text)
build_baseline(records)
compare_recent_pattern(baseline, recent_records)
combine_signals(assessment, behavior, emotion)
```

- `analyze_diary(text)`: 텍스트를 받아 `EmotionAnalysis` 반환
- `build_baseline(records)`: 일별 기록 목록을 받아 `BehavioralBaseline` 반환
- `compare_recent_pattern(baseline, recent_records)`: 개인 기준과 최근 기록을
  비교해 `PatternChangeResult` 반환
- `combine_signals(assessment, behavior, emotion)`: 세 출처를 구분해
  `CombinedSignalResult` 반환

현재 구현에서 위 `assessment`, `behavior`, `emotion` 인자는 각각
`AssessmentSignal`, `BehaviorSignal`, `EmotionSignal`이다. 원본 모델을 이
상태 모델로 바꾸는 버전별 정책과 오케스트레이션 함수는 향후 구현
범위이며, 결합 함수가 원본 설문 점수를 임의로 재해석하지 않게 분리한다.

`NEW_PATTERN_CHANGE`는 `BehaviorSignal.is_new_pattern=true`라는 명시적
근거가 있을 때만 생성한다. `MULTIPLE_SIGNALS_ALIGNED`는 실제 평가된
신호 두 개 이상이 같은 `SignalAlignmentDirection`을 제공할 때만 생성한다.
Assessment 방향은 버전이 관리되는 이전 기준점 비교에서 변화가 확인되어
`AssessmentSignal.is_change_from_prior_anchor=true`인 경우에만 포함한다.
고정된 elevated Assessment 자체에는 방향을 부여하거나 정렬 근거로 세지
않는다.
방향이 없거나 서로 다르지만 여러 신호가 존재하면 중립적인
`multiple_signals_present` 결과를 사용하며 정렬 Reason Code를 붙이지
않는다.

정확한 Python 타입 시그니처, 비동기 여부, 오류 타입과 배치 처리 방식은
구현 단계의 `TODO`다.

## 오류와 버전 처리 후보

- 입력 스키마 오류는 누락 데이터와 구분해 명시적으로 반환한다.
- 모델 미학습·선택 의존성 미설치는 사용자 상태 결과로 변환하지 않고 운영
  오류로 처리한다.
- 모델 로딩 및 예측 실패는 `EmotionAnalyzerError` 계층으로 반환하고 원래
  구현 예외는 exception chaining으로 보존한다.
- 데이터 부족은 오류로 숨기지 않고 출력의 `data_sufficiency`와
  `missing_signals`로 표현한다.
- 모든 계산 결과에는 모델 또는 규칙 버전을 포함한다.
- 같은 요청의 재시도와 결과 보존 정책은 백엔드에서 멱등성 키와 함께
  검토한다.

## 사람 검토 및 TODO

- DB 정규화, 보관 기간, 삭제·정정 이력과 개인정보 접근 권한
- 일기 원문 저장 여부와 재분석 정책
- 사용자 시간대 및 날짜 경계
- 자체 초기 설문의 차원, 척도, 버전
- 지표별 커버리지 집계와 자동·수동 출처 충돌 정책
- Behavioral Baseline 지표별 최소 유효 일수와 모든 변화 임계값
- `is_new_pattern`과 `SignalAlignmentDirection`을 산출하는 상류 정책
- combined level을 사용자에게 표시할 문구와 이유 코드 우선순위
- 함수별 정확한 오류 계약과 API 버전 전략

현재 문서의 기간 후보와 합성 값은 MVP 실험을 준비하기 위한 초안이다.
알고리즘 임계값은 확정 전이며 의료적 기준으로 사용하지 않는다.
