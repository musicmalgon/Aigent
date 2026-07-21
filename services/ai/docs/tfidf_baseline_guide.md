# 누수 방지 TF-IDF baseline 가이드

## 데이터와 라벨 결정

이 baseline은 JSON 원천만 사용한다. 예측 라벨은 승인된
`$.profile.emotion.type` 하나이며, `$.profile.emotion.emotion-id`는 특징과
예측 라벨 모두에서 제외한다. 후자는 희소하고 Training 전용 값이 확인되어
일반화 평가용 라벨로 사용하지 않는다.

입력 텍스트는 `HS01`, `HS02`, `HS03` 사용자 발화만을 순서대로 연결한다.

- HS01과 HS02는 필수다.
- HS03은 null 또는 빈 문자열이면 생략한다.
- 발화 사이에는 ` [TURN] ` 구분자를 넣는다.
- SS01–SS03 시스템 응답, persona, situation, emotion-id, talk-id, profile-id는
  특징에 포함하지 않는다.

## 내부 group-safe split

공식 Training과 Validation에는 raw talk-id와 profile-id의 큰 교집합이 확인되었다.
따라서 공식 분할 점수는 최종 일반화 성능으로 해석하면 안 된다.

raw talk-id는 데이터 전체에서 전역 고유 ID가 아닐 수 있다. 서로 다른
profile-id 아래에서 같은 raw talk-id 문자열이 반복될 수 있으므로, raw talk-id
교집합은 참고 통계로만 기록하며 분할 후보를 탈락시키지 않는다. 대화의 검증용
고유 키는 `(profile-id, talk-id)` 복합키다.

스크립트는 두 JSON을 내부적으로 합친 뒤 profile-id를 그룹으로 하여 새
Train/Validation/Test 분할을 만든다. 여러 `GroupShuffleSplit` 후보를 생성하고,
다음 조건을 만족하는 후보 중 클래스 분포 편차와 크기 편차가 가장 작은 후보를
선택한다.

- 목표 비율: 0.8 / 0.1 / 0.1
- profile-id 교집합 0
- `(profile-id, talk-id)` 복합키 교집합 0
- raw talk-id 교집합은 허용하고 참고 통계로 기록
- 가능한 범위의 `emotion.type` 클래스 분포 유지
- 기본 random state: 42
- 기본 후보 수: 200개, 유효 후보가 없을 때 한 번 1,000개까지 확장

모든 `emotion.type` 클래스는 내부 Train에 있어야 한다. Validation 또는 Test에
일부 클래스가 없을 수 있는 경우에는 즉시 실패하지 않고, 누락 클래스 수를 후보
점수와 출력 경고에 반영한다.

2단계 분할에서 temporary profile 그룹이 하나만 남아 Validation/Test로 나뉠 수
없는 경우를 피하기 위해, temporary에는 최소 두 profile 그룹이 남도록 비율을
보정한다. 따라서 작은 profile 수에서는 정확히 80/10/10이 아니라 가장 가까운
안전한 비율이 선택될 수 있다.

유효 후보가 끝내 없으면 `split_failure_diagnostics.json`에 레코드·profile·클래스
집계와 후보 실패 사유별 개수만 저장한다. ID, 텍스트, 경로, 해시, digest는
저장하지 않는다.

정규화 텍스트 중복은 보고하지만, 같은 문장이 서로 다른 profile 그룹에 있다면
그 자체로 분할을 불가능하게 만들지는 않는다. 의미적·부분 중복은 별도 검토가
필요하다.

## 모델과 선택 절차

기본 실험은 다음 둘이다.

- word TF-IDF: word 1–2gram, `min_df=3`, `max_df=0.98`, sublinear TF
- char TF-IDF: char_wb 2–5gram, `min_df=3`, sublinear TF

`--include-combined`를 지정하면 word와 char를 `FeatureUnion`으로 합친 세 번째
실험도 실행한다. 모든 실험은 `LogisticRegression(class_weight="balanced")`를
사용한다.

벡터라이저와 분류기는 내부 Train에만 적합한다. 내부 Validation macro-F1으로
설정을 선택하며, 선택 후 내부 Test는 한 번만 평가한다. 공식 Validation 평가는
참고용 파일로 별도 저장되며 최종 성능으로 표현하면 안 된다.

## 실행 방법

실제 AI Hub JSON은 사용자 로컬에서만 읽는다. 모든 경로는 절대경로여야 한다.

```bash
cd /path/to/Aigent

python ai/scripts/train_tfidf_baseline.py \
  --train-json "/absolute/path/to/Training.json" \
  --validation-json "/absolute/path/to/Validation.json" \
  --output-dir "/absolute/path/to/tfidf-baseline-output"
```

작은 합성 검증용 데이터에서만 `--min-df 1`을 사용할 수 있다. 실제 baseline의
기본값은 `min_df=3`이다.

## 저장 산출물

`--output-dir`에는 다음만 저장한다.

- `split_summary.json`: 분할별 수·그룹 수·클래스 분포·교차 분할 누수 개수
- `split_failure_diagnostics.json`: 분할 불가 시 안전한 구조·후보 집계 진단
- `validation_metrics.json`: 실험별 내부 Validation 지표와 선택 모델
- `test_metrics.json`: 선택 모델의 한 번의 내부 Test 지표
- `official_validation_metrics.json`: 참고용 공식 Validation 지표
- `model.joblib`, `vectorizer.joblib`: 선택된 내부 모델과 벡터라이저
- `label_classes.json`, `run_config.json`, `README.md`

저장하지 않는 항목은 원문 대화, talk-id, profile-id, 개별 예측, 미매칭 ID,
해시, digest 및 입력 절대경로다.

## 라이선스와 원본 비커밋 원칙

AI Hub 데이터의 라이선스와 이용 조건은 사용자가 적용 범위를 확인해야 한다.
원본 JSON, 대화문, ID, 파생된 레코드 수준 파일은 저장소에 커밋하지 않는다.
코드·테스트에는 합성 데이터만 둔다.
