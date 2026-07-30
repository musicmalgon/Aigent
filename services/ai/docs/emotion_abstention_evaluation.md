# Emotion Taxonomy v2 abstention 평가

이 도구는 모델이나 운영 threshold를 변경하지 않고
`confidence >= 0.65` 및 `margin >= 0.15` 정책의 제품 품질을 측정한다.
모델 추론은 평가 데이터마다 한 번만 실행하고, 저장된 confidence와 margin을
35개 threshold 조합에서 재사용한다.

## 지표 정의

- `acceptance_rate`: 전체 샘플 중 confidence와 margin 조건을 모두 통과한 비율
- `accepted_precision` / `accepted_accuracy`: 채택된 top-1 예측 중 정답 비율
- `accepted_macro_f1`: 6개 클래스별 선택적 precision/recall/F1의 macro 평균
- 클래스별 precision: 해당 클래스로 채택된 예측 중 정답 비율
- 클래스별 recall: 해당 클래스의 전체 정답 샘플 중 올바르게 채택된 비율
- `neutral_false_positive_rate`: 중립 정답 샘플 중 감정으로 채택된 비율

클래스별 recall의 분모에는 abstain된 정답 샘플도 포함한다. 채택 샘플이 하나도
없으면 채택 관련 비율은 `0.0`이다. 중립 샘플이 없으면
`neutral_false_positive_rate`는 `null`이며, 이는 `0.0`과 다르다.

## 기존 private test split 평가

원본 데이터와 private split assignment는 로컬 전용이며 Git이나 shareable 모델
artifact에 포함하지 않는다. PowerShell 예시는 다음과 같다.

```powershell
$repo = "C:\Users\lee\workspace\rewind\Aigent"
$artifact = "C:\remind-models\klue-roberta-remind-coarse-v2-e25e28"
$split = "C:\remind-models\tfidf-remind-coarse-v2-e25e28\private\split_assignment.json"
$output = "C:\remind-models\klue-roberta-remind-coarse-v2-e25e28\abstention-evaluation"

cd $repo

python services\ai\scripts\evaluate_emotion_abstention.py `
  --artifact-dir $artifact `
  --train-json "C:\Users\lee\workspace\rewind\emotional-dialogue\label\Training.json" `
  --validation-json "C:\Users\lee\workspace\rewind\emotional-dialogue\label\Validation.json" `
  --split-assignment $split `
  --dataset-identifier "aihub-emotional-dialogue-local-r1" `
  --model-version "klue-roberta-remind-coarse-v2-e25e28" `
  --device cuda `
  --batch-size 32 `
  --output-dir $output
```

첫 실행은 다음 파일을 생성한다.

```text
scored_predictions.jsonl
current_threshold_metrics.json
threshold_grid.json
threshold_grid.csv
confidence_bins.json
margin_bins.json
```

`scored_predictions.jsonl`에는 원문이나 사용자 ID가 없고 정답 라벨, top-1 라벨,
confidence, margin만 있다. 같은 점수로 grid만 다시 계산하려면 모델을 로드하지
않고 실행한다.

```powershell
python services\ai\scripts\evaluate_emotion_abstention.py `
  --scored-predictions "$output\scored_predictions.jsonl" `
  --dataset-identifier "aihub-emotional-dialogue-local-r1" `
  --model-version "klue-roberta-remind-coarse-v2-e25e28" `
  --output-dir "$output\recomputed"
```

AI Hub test split에는 중립 클래스가 없으므로 이 실행의 neutral FPR은 `null`이다.
중립 성능을 판단하려면 별도의 사람이 검토한 calibration set이 필요하다.

## 고정 calibration set

제품 입력 계약과 동일하게 각 행은 사용자 발화 2개 또는 3개를 제공한다. 부가
검수 metadata는 보존할 수 있지만 모델 입력이나 평가 출력에는 포함하지 않는다.

```json
{"id":"cal-v1-001","turns":["오늘은 특별한 일이 없었어.","평소처럼 하루를 보냈어."],"label":"중립","difficulty":"medium","boundary":"감정-중립","reviewed_by":["reviewer_1","reviewer_2"]}
{"id":"cal-v1-002","turns":["해야 할 일이 있는데 손이 안 가.","시작할 힘도 없고 계속 누워 있고 싶어."],"label":"무기력","difficulty":"medium","boundary":"무기력-슬픔","reviewed_by":["reviewer_1","reviewer_2"]}
```

허용 정답은 `분노/기쁨/불안/당황/슬픔/무기력/중립`이다. 이 파일은 검수 완료 후
`services/ai/data/evaluation/emotion_calibration_v1.jsonl`로 버전 관리할 수
있지만, 실제 사용자 문장이나 개인정보를 넣으면 안 된다.

```powershell
python services\ai\scripts\evaluate_emotion_abstention.py `
  --artifact-dir $artifact `
  --calibration-jsonl "services\ai\data\evaluation\emotion_calibration_v1.jsonl" `
  --dataset-identifier "emotion-calibration-v1" `
  --model-version "klue-roberta-remind-coarse-v2-e25e28" `
  --device cuda `
  --batch-size 32 `
  --output-dir "C:\remind-models\emotion-calibration-v1-results"
```

## Threshold 선택

grid는 다음 조합을 고정해서 계산한다.

```text
confidence: 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80
margin:     0.05, 0.10, 0.15, 0.20, 0.25
```

초기 MVP 판단 기준은 accepted precision `>=0.85`, neutral FPR `<=0.05`를
충족하는 조합 중 acceptance rate와 무기력 precision을 비교하는 것이다. 이
기준은 모델 교체나 운영 threshold 변경을 자동으로 수행하지 않는다.

## 현재 v2 모델의 diagnostic 결과

2026-07-30에 `klue-roberta-remind-coarse-v2-e25e28`을 고정 private test
4,993건에 실행했다. 캐시된 top-1 결과의 raw accuracy는 기존
`test_metrics.json`과 동일한 `0.706790`으로 재현됐으며 abstention 결과는
다음과 같다.

| Confidence | Margin | Acceptance | Accepted precision | Accepted macro-F1 | 무기력 precision | 무기력 recall | 무기력 F1 |
| ----------: | -----: | ---------: | -----------------: | ----------------: | ---------------: | ------------: | --------: |
| 0.65 | 0.15 | 0.771680 | 0.797301 | 0.663304 | 0.734940 | 0.316062 | 0.442029 |
| 0.70 | 0.15 | 0.735830 | 0.812738 | 0.654846 | 0.760000 | 0.295337 | 0.425373 |
| 0.75 | 0.15 | 0.695574 | 0.825223 | 0.642211 | 0.774648 | 0.284974 | 0.416667 |
| 0.80 | 0.15 | 0.650711 | 0.843336 | 0.630150 | 0.818182 | 0.279793 | 0.416989 |

35개 조합 중 accepted precision `0.85` 이상을 만족하는 조합은 없었다.
confidence가 `0.65` 이상인 구간에서는 이번 test 결과에서 margin `0.05~0.25`
변경이 acceptance를 추가로 바꾸지 않았다. 이 결과는 현재 모델의 문제를
진단하기 위한 것이며 test 결과로 운영 threshold를 선택하면 안 된다. 중립
샘플도 없으므로 calibration set 검수와 평가가 끝날 때까지 현 정책을 자동으로
변경하지 않는다.
