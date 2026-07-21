# 로컬 데이터 스키마 승인 검사 가이드

## 목적

`inspect_dataset_schema_local.py`는 TF-IDF baseline을 만들기 전에 XLSX 헤더,
JSON 키 구조, 필드 역할 및 연결 키를 사람이 승인할 수 있도록 집계 보고서를
생성한다.

이 도구는 데이터 내용을 검토하는 도구가 아니다. 출력에는 필드 이름과 집계
통계만 포함되며 레코드 값, 문장, ID 값, 미매칭 키 목록, 해시, digest 및 입력
절대경로를 저장하지 않는다.

## Codex가 원본 데이터를 읽지 않는 이유

원본 데이터에는 대화 문장, 사용자 또는 대화 식별자, 개인정보가 포함될
가능성이 있다. 스키마를 확정하는 데 필요한 정보는 필드 이름과 구조적 통계로
제한할 수 있으므로 원본 값을 Codex 세션으로 전달할 필요가 없다.

다음 원칙을 지킨다.

- 실제 AI Hub 파일에 대한 명령은 사용자가 자신의 로컬 터미널에서 실행한다.
- Codex에는 원본 XLSX, JSON, 레코드 일부, ID, 문장 또는 해시를 공유하지 않는다.
- 개발 테스트에는 합성 fixture만 사용한다.
- 출력 보고서도 공유 전에 안전 출력 정책과 경고를 확인한다.

## 로컬 실행

저장소의 `ai` 디렉터리에서 실행하는 예시는 다음과 같다. 모든 입력과 출력
경로는 절대경로여야 한다.

```bash
python scripts/inspect_dataset_schema_local.py \
  --train-source-xlsx "/absolute/path/to/train-source.xlsx" \
  --train-label-json "/absolute/path/to/train-label.json" \
  --validation-source-xlsx "/absolute/path/to/validation-source.xlsx" \
  --validation-label-json "/absolute/path/to/validation-label.json" \
  --output "/absolute/path/to/schema-inspection.json"
```

자동 헤더 또는 JSON 레코드 경로가 불확실하면 보고서의 후보만 검토한다.
사용자가 구조를 확인한 뒤 다음과 같이 명시적으로 다시 실행할 수 있다.

```bash
python scripts/inspect_dataset_schema_local.py \
  --train-source-xlsx "/absolute/path/to/train-source.xlsx" \
  --train-label-json "/absolute/path/to/train-label.json" \
  --validation-source-xlsx "/absolute/path/to/validation-source.xlsx" \
  --validation-label-json "/absolute/path/to/validation-label.json" \
  --output "/absolute/path/to/schema-inspection.json" \
  --train-xlsx-header-row 1 \
  --validation-xlsx-header-row 1 \
  --train-json-record-path '$.records' \
  --validation-json-record-path '$.records'
```

연결 키 통계를 계산하려면 XLSX와 JSON 필드를 쌍으로 지정한다.

```bash
python scripts/inspect_dataset_schema_local.py \
  --train-source-xlsx "/absolute/path/to/train-source.xlsx" \
  --train-label-json "/absolute/path/to/train-label.json" \
  --validation-source-xlsx "/absolute/path/to/validation-source.xlsx" \
  --validation-label-json "/absolute/path/to/validation-label.json" \
  --output "/absolute/path/to/schema-inspection.json" \
  --train-xlsx-id-column "approved_train_id_column" \
  --train-json-id-field '$.records[].approved_train_id_field' \
  --validation-xlsx-id-column "approved_validation_id_column" \
  --validation-json-id-field '$.records[].approved_validation_id_field'
```

명시한 컬럼이나 JSON 필드가 없으면 도구는 즉시 실패한다. XLSX 컬럼은
1-based 위치 번호로도 지정할 수 있다.

## 교차 분할 누수 검사

후보 필드는 자동으로 누수 검사에 사용되지 않는다. 사용자가 Training과
Validation 필드를 모두 명시한 검사만 실행된다.

- source ID: 각 분할의 `--*-xlsx-id-column`
- 그룹 ID: `--train-group-field`, `--validation-group-field`
- 대화 ID: `--train-conversation-field`, `--validation-conversation-field`
- 텍스트: `--train-text-field`, `--validation-text-field`

같은 이름이 XLSX와 JSON 양쪽에 있어 모호할 때는 `xlsx:` 또는 `json:` 접두사를
사용한다.

```text
--train-text-field xlsx:utterance_text
--validation-text-field xlsx:utterance_text
```

텍스트 중복 비교에는 다음 정규화만 적용된다.

- Unicode NFC
- 앞뒤 공백 제거
- 연속 공백을 한 칸으로 축약
- ASCII 영어 대문자를 소문자로 변환

실제 중복 텍스트나 비교용 해시는 출력하지 않고 개수와 비율만 출력한다.

## 출력 JSON에서 확인할 항목

### `safe_output_policy`

값, 텍스트, ID, 미매칭 키, 해시, digest 및 입력 절대경로가 직렬화되지
않는다는 정책을 확인한다.

### `splits.*.xlsx_schema`

- 시트 이름, 상태, `max_row`, `max_column`
- 헤더 행 번호, 상태, 신뢰도 및 점수
- 각 컬럼의 1-based 위치와 안전한 표시명
- 타입별 개수, 결측 수, 고유값 개수 또는 안전한 상한
- 문자열 길이의 count, min, max, mean, p50, p95

자동 탐지가 충분히 강하지 않으면 헤더 문자열은 노출하지 않고 생성된 컬럼명을
사용한다. 이 경우 헤더 행을 확인한 다음 `--*-xlsx-header-row`로 명시해 다시
실행한다.

### `splits.*.json_schema`

- 최상위 타입
- 레코드 배열 경로 후보와 선택 결과
- 레코드 수
- 모든 키 경로의 존재·결측·타입 통계
- 배열 길이, 객체의 하위 키 및 문자열 길이 통계

자동으로 선택된 레코드 경로도 승인된 것으로 간주하지 않는다.

### `role_candidates`

필드 이름과 구조만 이용한 역할 후보다. 모든 후보는 `approved: false`이며 실제
값, 문자열 길이 또는 정수 타입만으로 텍스트·ID 역할을 확정하지 않는다.

### `join_candidates`

값을 출력하지 않고 양쪽의 non-null, unique, duplicate, intersection,
한쪽에만 존재하는 키 수, match rate 및 관계 후보를 보여준다. 통계가 좋아도
키 의미와 관계를 사람이 승인하기 전에는 학습 데이터 결합에 사용하지 않는다.

### `cross_split_checks`

사용자가 명시한 source ID, 그룹 ID, 대화 ID 또는 텍스트 검사만
`completed`로 표시된다. `not_run`은 중복이 없다는 뜻이 아니다.

### `decisions_required`

TF-IDF 구현 전에 사람이 결정해야 하는 내용을 기계 판독 가능한 목록으로
제공한다. 후보와 통계는 결정 근거일 뿐 자동 승인이 아니다.

## 후보와 승인된 필드의 차이

후보는 이름이나 구조가 특정 역할과 유사하다는 뜻이다. 라벨 의미, 식별 범위,
대화 경계 또는 사용자 경계를 보장하지 않는다.

승인은 데이터 제공 명세와 담당자의 확인을 통해 다음을 결정하는 별도
절차다.

- 입력 텍스트 필드
- 라벨 필드와 라벨 체계
- source ID 및 label ID
- 대화·사용자·그룹 필드
- XLSX–JSON의 관계와 결합 정책
- Training–Validation 분리 단위

도구는 승인 결과를 자동으로 기록하거나 후보의 `approved` 값을 `true`로
바꾸지 않는다.

## 행 순서 기반 결합 금지

XLSX 행과 JSON 레코드 수가 같거나 배열 순서가 비슷하더라도 행 위치를 연결
키로 사용하면 안 된다. 헤더, 빈 행, 제외 레코드, 정렬 차이 또는 중복으로
잘못된 라벨이 결합될 수 있다.

명시적으로 승인된 키에 대해 일대일 또는 의도한 관계가 확인되고, 미매칭과
중복 처리 정책이 정해진 뒤에만 결합한다.

## 안전하게 공유할 수 있는 범위

일반적으로 이 도구가 정상 완료하며 생성한 JSON 보고서만 공유 대상으로
고려할 수 있다. 공유 전에는 다음을 다시 확인한다.

- `safe_output_policy`의 모든 비공개 항목이 `false`인지 확인
- 입력 절대경로가 없는지 확인
- 레코드 값, 문장, ID 값, 이메일·전화번호 값이 없는지 확인
- 해시, digest, 미매칭 키 목록 및 특정 행 번호가 없는지 확인
- 헤더와 JSON 키 이름도 조직의 공유 정책상 허용되는지 확인

오류 로그에는 경로 또는 값을 추가해 공유하지 않는다.

## TF-IDF 구현 전 필수 승인 체크리스트

- [ ] Training과 Validation의 XLSX 헤더 행 승인
- [ ] Training과 Validation의 JSON 레코드 경로 승인
- [ ] 입력 텍스트 필드와 필요한 문맥 필드 승인
- [ ] 라벨 필드, 클래스 의미 및 결측 라벨 정책 승인
- [ ] XLSX ID와 JSON ID의 의미 및 연결 관계 승인
- [ ] 중복 키와 미매칭 레코드 처리 정책 승인
- [ ] 사용자·대화·그룹 중 실제 분할 단위 승인
- [ ] 동일 source ID의 교차 분할 중복 검사 완료
- [ ] 동일 사용자·대화·그룹의 교차 분할 중복 검사 완료
- [ ] 정규화 텍스트 중복 검사 완료
- [ ] 파생·부분·의미 중복에 대한 별도 검사 정책 승인
- [ ] 벡터라이저를 Training에만 적합하고 Validation에는 변환만 적용하도록 승인
- [ ] 라벨, ID, 분할 정보 및 사후 생성 필드가 특징에서 제외되는지 승인
