# emotional-dialogue 로컬 데이터 감사 가이드

## 목적과 안전 경계

이 가이드는 허용된 `emotional-dialogue` 데이터의 구조를 사용자가 자신의
로컬 환경에서 직접 확인하기 위한 절차다. 원본 데이터와 감사 출력은 Codex
작업 폴더 밖의 접근이 제한된 로컬 경로에 보관한다.

확인된 파일 배치는 다음과 같다. 파일 내용, 실제 필드명, 라벨명, ID 연결
방식은 아직 확인된 사실로 간주하지 않는다.

```text
emotional-dialogue/
├── label/
│   ├── Training.json
│   └── Validation.json
└── original/
    ├── Training.xlsx
    └── Validation.xlsx
```

이 감사는 구조와 집계만 확인한다. 원문 샘플, 실제 ID, group 값, 입력
절대경로 또는 복원 가능한 digest를 결과에 기록하지 않는다. 데이터 다운로드,
복사, 이동, 모델 학습 및 라벨 매핑도 수행하지 않는다.
입력 절대경로와 원문은 출력 JSON뿐 아니라 stdout, stderr 및 예외
메시지에도 포함되면 안 된다.

## 준비

Python 3.11 이상 환경에서 저장소의 개발 의존성을 설치한다.
`openpyxl`은 XLSX를 읽기 위한 직접 의존성이다.

```bash
cd <REPOSITORY_ROOT>
python -m pip install -r ai/requirements-dev.txt
```

원본 및 라벨 파일과 감사 결과 파일은 Git 저장소 안에 두지 않는다. 실행 전
데이터셋 이용약관이 로컬 분석과 집계 결과 생성을 허용하는지 확인하고, 감사
결과의 보관·전달·파생 이용 조건도 사용자가 직접 확인해야 한다.

## 실행

저장소 루트에서 다음 명령을 실행한다. 네 입력 파일과 출력 파일, 총 다섯
인자는 모두 필수다.

```bash
python ai/scripts/audit_dataset_local.py \
  --train-source-xlsx "<DATASET>/original/Training.xlsx" \
  --train-label-json "<DATASET>/label/Training.json" \
  --validation-source-xlsx "<DATASET>/original/Validation.xlsx" \
  --validation-label-json "<DATASET>/label/Validation.json" \
  --output "<PRIVATE_OUTPUT>/audit_summary.json"
```

실제 구조를 사람이 확인한 뒤에만 다음 선택 인자를 지정한다.

- `--source-id-field`: 원천 XLSX의 연결 ID 필드
- `--label-id-field`: 라벨 JSON의 연결 ID 필드
- `--text-field`: 원문 필드
- `--label-field`: 라벨 필드
- `--group-field`: 동일 작성자·대화·문서 등을 나타내는 그룹 필드
- `--source-sheet`: 감사할 worksheet 이름
- `--encoding`: JSON 파일 인코딩

필드명을 모르는 상태에서는 임의 값을 지정하지 않는다. 공통 ID 후보가
여러 개이거나 구조가 모호하면 도구는 자동 연결하거나 평탄화하지 않고
`unresolved`와 후보만 보고해야 한다.

## XLSX 처리 원칙

원천 XLSX는 `openpyxl`의 `read_only=True`, `data_only=True` 모드로 읽는다.
워크북을 저장하거나 수정하지 않으며 수식 실행, 외부 연결 갱신, 매크로
실행을 하지 않는다.

- 기본 대상은 첫 번째 visible worksheet다.
- 여러 worksheet를 자동으로 합치지 않는다.
- `--source-sheet`를 지정하면 해당 sheet만 감사한다.
- hidden worksheet를 `--source-sheet`로 지정하면 셀을 읽지 않고 안전하게
  실패한다.
- 여러 sheet가 있으면 이름, 표시 상태, 행·열 수만 집계한다.
- hidden sheet는 존재 여부만 경고하고 셀 내용을 노출하지 않는다.
- 셀 원문과 샘플 행을 출력하지 않는다.

결과에는 행·열 수, 헤더 후보, 필드별 결측·타입 집계, 중복 행 수, 텍스트
길이 통계, ID 및 group ID 후보 같은 비식별 집계만 포함한다.

## JSON 구조 탐지 원칙

라벨 JSON은 최상위 배열, 최상위 객체의 `records` 또는 `data` 배열, 파일별
annotation 객체와 중첩 annotation 배열을 구조 후보로 탐지한다. 후보
경로가 모호하면 자동으로 하나를 선택하거나 레코드를 임의 평탄화하지 않는다.

라벨 데이터에 원문 형태 필드가 포함되어도 값은 출력하지 않고 존재 여부만
보고한다. 문자열 라벨 값과 빈도는 사람이 의미가 명확한 `--label-field`를
명시하고, 값이 반복되며 `category`, `class`, `label`, `emotion` 같은 범주
표지가 포함된 공백 없는 짧은 기계 토큰이고 고유 값 수가 제한된 경우에만
포함한다. 자동 탐지한 라벨 필드의 문자열 값과 사람 이름처럼 범주임을
보수적으로 확인할 수 없는 값은 기본적으로 숨긴다.
자유서술형, 문장·대화 형태, 비정상적으로 많은 고유 값 또는 개인정보
가능성이 있으면 값을 숨기고 다음 정보만 기록한다.

- `label_values_redacted: true`
- `distinct_label_count`
- 사람이 직접 확인해야 한다는 warning

## 원천·라벨 연결과 split 보존

연결은 행 순서가 아니라 다음 우선순위를 따른다.

1. 사용자가 지정한 `--source-id-field`와 `--label-id-field`
2. 원천과 라벨에서 관찰된 단 하나의 공통 ID 후보
3. 연결 불가를 뜻하는 `unresolved`

공통 후보가 여러 개면 자동 선택하지 않는다. 실제 ID나 매칭된 행은 출력하지
않고, 레코드 수·매칭 수·한쪽에만 있는 수·중복 키 수·모호한 매칭 수만
집계한다.

JSON 레코드 구조, 라벨 필드 또는 연결 키가 미해결이면 계산할 수 없는
레코드·라벨·매칭 통계는 숫자 `0`이 아니라 `null`로 기록한다. 선택된 빈
배열이나 실제 집계값이 0인 경우와 감사 불가 상태를
`statistics_available`, `label_statistics_available`, warning,
`join_status`로 구분한다.

공식 Training과 Validation은 항상 별도로 보존한다.

- Training 원천은 Training 라벨과만 연결한다.
- Validation 원천은 Validation 라벨과만 연결한다.
- 두 split을 합치거나 새로 분할하지 않는다.
- Validation을 학습 데이터로 사용하지 않는다.
- 감사 과정에서 모델을 학습하지 않는다.
- Training과 Validation에 서로 다른 연결 키를 자동 선택하지 않는다.

교차 split 감사는 동일 source ID, 동일 group ID, 동일 원문 등 누수 가능성의
건수만 계산한다. 원문 비교용 digest가 필요하면 프로세스 메모리 안에서만
사용하며 출력이나 별도 파일로 저장하지 않는다.

XLSX 자체는 read-only streaming으로 순회하지만, 정확한 중복·연결·교차
누수 집계를 위해 선택된 ID·group·text와 행의 digest 개수는 서로 다른 값의
수에 비례해 메모리에 유지된다. 대용량 파일에서는 실행 전 사용 가능한
메모리를 확인한다.

## 결과를 전달하기 전 사람 검토

`<PRIVATE_OUTPUT>/audit_summary.json`은 Codex 또는 다른 사람에게 전달하기
전에 사용자가 직접 열어 다음을 확인한다.

1. 실제 입력 절대경로가 없는가
2. 원문 전체나 일부, 실제 ID 및 group 값이 없는가
3. 텍스트 digest나 행 단위 정보처럼 복원 가능한 정보가 없는가
4. 자유서술형 또는 개인정보 가능성이 있는 라벨 값이 비공개 처리됐는가
5. Training과 Validation 통계가 분리돼 있는가
6. warning과 limitation에 구조가 모호한 부분이 남아 있는가

원문 부재를 확인하기 전에는 출력 파일을 Codex 작업 공간에 복사하거나
내용을 대화에 붙여 넣지 않는다. 원본 XLSX·JSON과 감사 출력 JSON을 Git에
추가하거나 커밋하지 않는다.

## 감사 이후 사람이 결정할 사항

감사 결과는 라벨 매핑 승인이나 학습 허가가 아니다. 다음 사항은 결과의
warning과 후보를 검토한 뒤 사람이 별도로 결정한다.

- 실제 원문·라벨·ID·group 필드
- 원천 XLSX와 라벨 JSON의 공식 연결 키
- 중복 및 미연결 레코드 처리 정책
- 라벨 값 공개가 안전한지 여부
- Training/Validation 교차 누수의 처리 방법
- 원본 라벨을 Re:Mind 라벨로 매핑할지 여부와 승인된 매핑 버전
- 데이터셋과 감사 출력의 보관·이용·전달 조건

별도 승인이 있기 전까지 실제 라벨을 임의로 해석하거나
`stable`, `fatigue`, `anxiety`, `other`로 매핑하지 않는다.
