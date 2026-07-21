# 감정 라벨 로컬 감사 가이드

## 목적

`audit_emotion_labels_local.py`는 공식 Training·Validation JSON 분할을 변경하지
않고, TF-IDF baseline 전에 라벨 분포·상황 항목·대화 그룹 누수·텍스트 중복을
집계한다.

도구는 확정된 다음 경로만 사용한다.

- 감정 유형: `$.profile.emotion.type`
- 세부 감정: `$.profile.emotion.emotion-id`
- 상황: `$.profile.emotion.situation`
- 사용자 발화: `$.talk.content.HS01`–`HS03`
- 시스템 응답: `$.talk.content.SS01`–`SS03`
- 대화 ID: `$.talk.id.talk-id`
- 프로필 ID: `$.talk.id.profile-id`

## 원본 데이터 보호

Codex는 실제 AI Hub JSON을 열거나 읽지 않는다. 실행은 사용자의 로컬 터미널에서
수행하며, 결과에는 다음을 저장하지 않는다.

- 사용자 또는 시스템 대화 문장
- talk-id, profile-id, 미매칭 ID 목록
- 원문·정규화 텍스트, 해시, digest
- 입력 절대경로

라벨 값과 라벨별·상황별 집계 수는 스키마 승인과 클래스 평가에 필요한 범위에서
출력한다. 결과를 공유하기 전 `safe_output_policy`가 기대한 값인지 확인한다.

## 실행 방법

`ai/` 디렉터리에서 모든 경로를 절대경로로 지정해 실행한다.

```bash
python scripts/audit_emotion_labels_local.py \
  --train-json "/absolute/path/to/Training.json" \
  --validation-json "/absolute/path/to/Validation.json" \
  --output "/absolute/path/to/emotion-label-audit.json"
```

상대경로, 동일 파일을 Training과 Validation에 중복 지정하는 경우, 또는 루트가
배열이 아닌 JSON은 안전한 오류와 함께 실패한다. 오류에 경로나 레코드 값은
포함되지 않는다.

## 출력 확인 항목

### 분할별 통계

- `record_count`: 루트 배열 레코드 수
- `emotion_type_distribution`, `emotion_id_distribution`: 고유값, 클래스 수,
  빈도·비율, null 수, 최소 클래스 빈도, 불균형 비율
- `situation_distribution`: 배열 길이, 고유 상황 항목 수와 빈도
- `utterance_statistics`: HS01–HS03별 존재·null 수, 연결 샘플 수, 길이 통계,
  빈 텍스트 수
- `system_response_statistics`: SS01–SS03별 존재·null 수만 제공
- `id_statistics`: talk-id·profile-id 고유 수, 중복 talk-id 수,
  프로필당 고유 대화 수 통계

사용자 발화는 HS01, HS02, HS03 순서로 비어 있지 않은 값을 줄바꿈으로 연결한다.
연결된 실제 값은 출력하지 않는다.

### 교차 분할 누수

`cross_split_leakage`에서 다음을 확인한다.

- 동일 talk-id와 profile-id의 개수 및 각 분할 내 비율
- 연결 사용자 발화의 완전 일치 개수
- NFC·공백 정리·ASCII 영문 소문자화 후의 일치 개수
- 같은 정규화 텍스트가 양 분할에서 다른 `(emotion.type, emotion-id)` 조합을
  가질 때의 충돌 수
- Training 전용·Validation 전용 emotion.type 및 emotion-id 클래스

이 검사는 의미적으로 비슷한 문장, 의역 또는 부분 중복을 찾지 않는다. 그 검사는
별도의 승인된 정책으로 수행해야 한다.

## TF-IDF baseline 전 검토

- [ ] 예측 라벨로 `emotion.type` 또는 `emotion.emotion-id` 중 하나를 승인
- [ ] 클래스 수, 최소 클래스 빈도, 불균형과 Validation 전용 클래스를 검토
- [ ] null 라벨·빈 사용자 발화의 제외 또는 처리 정책 승인
- [ ] HS01–HS03 연결 방식을 승인
- [ ] 동일 talk-id·profile-id가 교차 분할에 존재할 때 처리 방침 승인
- [ ] 완전·정규화 텍스트 중복 및 라벨 충돌을 검토
- [ ] 공식 분할을 유지할지, 승인된 그룹 단위 재분할을 추가할지 결정
- [ ] 벡터라이저는 Training에만 적합하고 Validation에는 변환만 적용하도록 구현
- [ ] ID, 시스템 응답, 라벨, 분할 정보는 특징에서 제외

## 승인 상태

`recommended_label_options`의 두 후보는 모두 `approved: false`로 출력된다.
도구는 라벨을 선택하거나 의미를 자동으로 승인하지 않는다. 승인 결정은 데이터
명세와 담당자 검토에 근거해 별도로 기록해야 한다.
