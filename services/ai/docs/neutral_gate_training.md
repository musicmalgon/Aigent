# Neutral gate 학습 및 운영

Neutral gate는 `neutral`과 `emotional`만 판별하는 별도
`klue/roberta-base` 이진 분류기다. 기존 Emotion Taxonomy v2의 여섯 감정
클래스는 변경하지 않는다.

```text
사용자 발화
→ neutral gate
  → neutral: 6-class 호출 생략, emotion=null
  → emotional: 기존 6-class + confidence/margin abstention
```

## 로컬 데이터 계약

학습 데이터는 Git에 커밋하지 않는 UTF-8 JSONL 파일이다. 각 행은 다음 필드만
허용한다.

```json
{"id":"opaque-001","group_id":"profile-001","split":"train","label":"neutral","turns":["오늘 수업에 갔다.","점심을 먹고 과제를 했다."]}
```

- `split`: `train`, `validation`, `calibration`, `test`
- `label`: `neutral`, `emotional`
- `turns`: 사용자 발화 2개 또는 3개
- 같은 `group_id`와 정규화된 동일 문장은 여러 split에 등장할 수 없다.
- 모든 split은 두 라벨을 모두 포함해야 한다.
- calibration과 test는 학습에 사용하지 않는다.
- test는 calibration threshold를 선택한 뒤 한 번만 평가한다.

권장 규모는 train 기준 클래스당 1,000~1,500개다. Emotional은 기존 6개
클래스에서 같은 수를 추출한다. Calibration은 neutral 100개와 emotional
120개 이상, final test는 neutral 150~200개와 emotional 180~240개를 권장한다.

배포 서버에서 발견한 중립 오탐 문장은
`data/evaluation/neutral_gate_regression_v1.jsonl`에 합성 회귀 fixture로
고정했다. 이 파일은 threshold 선택용 데이터가 아니다.

## GPU 학습

```powershell
cd C:\Users\lee\workspace\rewind\Aigent
.\.venv\Scripts\Activate.ps1

$dataset = "C:\remind-data\neutral-gate-v1.jsonl"
$output = "C:\remind-models\neutral-gate-klue-roberta-v1"

python services\ai\scripts\train_neutral_gate.py `
  --dataset-jsonl $dataset `
  --dataset-release-id "neutral-gate-local-r1" `
  --output-dir $output `
  --model-version "neutral-gate-klue-roberta-v1" `
  --model-name "klue/roberta-base" `
  --device cuda `
  --fp16 `
  --epochs 3 `
  --train-batch-size 8 `
  --eval-batch-size 16 `
  --gradient-accumulation-steps 2 `
  --max-length 128 `
  --learning-rate 2e-5 `
  --early-stopping-patience 1 `
  --random-state 777 `
  --num-workers 0
```

CLI는 validation macro-F1로 best checkpoint를 고른 후 calibration에서
`0.30..0.80` threshold를 탐색한다. 아래 최소 guard를 만족하지 못하면 artifact
생성을 실패시킨다.

```text
neutral FPR <= 0.10
emotional retention >= 0.90
```

목표 guard는 neutral FPR `<=0.05`, emotional retention `>=0.90`이다.

## Artifact

```text
neutral-gate-klue-roberta-v1/
├── model/
├── tokenizer/
├── label_classes.json
├── model_metadata.json
├── training_config.json
├── calibration_metrics.json
├── test_metrics.json
└── split_summary.json
```

원시 데이터, 사용자 식별자, optimizer state와 전체 checkpoint 디렉터리는
배포 artifact에 포함하지 않는다.

## 런타임 설정

```env
EMOTION_NEUTRAL_GATE_ENABLED=true
EMOTION_NEUTRAL_GATE_ARTIFACT_DIR=/models/neutral-gate
EMOTION_NEUTRAL_GATE_THRESHOLD=
EMOTION_NEUTRAL_GATE_MODEL_VERSION=
EMOTION_NEUTRAL_GATE_THRESHOLD_VERSION=mvp-v2-neutral-gate
EMOTION_NEUTRAL_GATE_DEVICE=auto
EMOTION_NEUTRAL_GATE_MAX_LENGTH=128
```

threshold와 model version을 비워두면 artifact metadata 값을 사용한다. 환경변수
override는 긴급 운영 변경용이며 변경 이력을 별도로 남겨야 한다.

Gate가 활성화됐는데 artifact를 읽지 못하면 readiness는 `503`이다. 추론 중 gate가
실패해도 6-class로 우회하지 않는다. 개발 환경은
`EMOTION_NEUTRAL_GATE_ENABLED=false`로 기존 파이프라인을 사용할 수 있다.

## 성능 측정

실제 서버에서 다음을 각각 측정한다.

- gate 단독 평균/p95 latency
- emotional 입력의 gate + 6-class 평균/p95 latency
- neutral 입력에서 6-class 생략 비율
- 컨테이너 시작 전후 RSS/VRAM
- 두 모델 로딩 시간과 readiness 전환 시간

결합 평가에는 원문이 아닌 캐시된 점수 JSONL을 사용한다. 각 행은
`true_gate_label`, `emotional_probability`, nullable `true_emotion`,
`predicted_emotion`, `confidence`, `margin`을 포함하고, 선택적으로
`gate_latency_ms`, `coarse_latency_ms`를 포함한다.

```powershell
python services\ai\scripts\evaluate_neutral_gate_pipeline.py `
  --scores-jsonl C:\remind-data\neutral-gate-combined-scores.jsonl `
  --gate-threshold 0.62 `
  --confidence-threshold 0.65 `
  --margin-threshold 0.15 `
  --output-json C:\remind-models\neutral-gate-combined-metrics.json
```

출력은 gate FPR/retention과 함께 accepted macro-F1, 무기력 recall,
결합 neutral false-positive rate, gate 및 gate+6-class p50/p95를 기록한다.
사용자 원문은 score 파일이나 로그에 저장하지 않는다.

## Rollback

1. `EMOTION_NEUTRAL_GATE_ENABLED=false`로 AI 런타임을 재시작한다.
2. 기존 v2 응답과 Risk Adapter 동작을 smoke test한다.
3. neutral-gate 이력이 DB에 존재하면 Alembic `20260731_0008` downgrade는
   의도적으로 중단된다. 이력 export 또는 명시적 삭제 없이 컬럼을 제거하지 않는다.
