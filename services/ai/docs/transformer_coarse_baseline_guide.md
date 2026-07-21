# Transformer 6-class 감정 대분류 Baseline

## 목적과 라벨

이 baseline은 기존 KLUE-RoBERTa 60-class 세부 감정 분류를 유지하면서 같은
사용자 발화와 leakage-safe split으로 다음 6개 감정 대분류를 학습한다.

| id | label |
|---:|---|
| 0 | 기쁨 |
| 1 | 불안 |
| 2 | 당황 |
| 3 | 분노 |
| 4 | 슬픔 |
| 5 | 상처 |

기존 fine 모드는 `--label-level fine`이며 CLI 기본값이다. Coarse 모드는
`--label-level coarse`로 명시한다. 두 실험은 label space가 달라 점수를 직접적인
성능 향상으로 비교할 수 없다. 결과는 의료 진단, 치료 또는 위기 판정이 아니다.

Inference 사용법과 응답 계약은
[`coarse_emotion_inference.md`](coarse_emotion_inference.md)를 참고한다.

## Mapping 근거

숫자 코드 범위를 추측해 mapping하지 않았다. 공식 AI Hub 원천 Excel의
`감정_대분류`, `감정_소분류`, `사람문장1~3`과 라벨링 JSON의
`profile.emotion.type`, `HS01~HS03`을 정규화해 조인했다. Training 및 Validation
58,268개 샘플이 모두 일치했고 unmatched/ambiguous 샘플은 각각 0개였다.

검토 가능한 source는
`services/ai/config/emotion_label_mapping.json`이다. 실행 전에 E10~E69 전체,
6개 coarse label의 고정 순서, class별 10개 code와 sample coverage를 검증한다.

## Split 및 평가 정책

- 입력은 `HS01`, `HS02`, optional `HS03`만 사용한다.
- system response, emotion metadata, profile/talk id는 model input에서 제외한다.
- 기존 TF-IDF seed와 candidate count로 profile-safe split을 재현한다.
- fine split signature를 검증한 후 label만 coarse로 변환한다.
- 새 random split을 만들지 않는다.
- validation macro-F1로 best checkpoint를 선택한다.
- internal test는 model selection 완료 후 정확히 한 번만 평가한다.

검증된 split은 train 46,792, validation 5,751, test 5,725이며 profile,
conversation key, normalized text overlap은 모두 0이다.

## 환경 준비

저장소 root에서 Python 3.12 virtual environment와 학습 의존성을 준비한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r services\ai\requirements-dev.txt
python -m pip install -r services\ai\requirements-transformer.txt
$env:PYTHONPATH = "services"
```

Linux/macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r services/ai/requirements-dev.txt
python -m pip install -r services/ai/requirements-transformer.txt
export PYTHONPATH=services
```

GPU 학습 전에는 설치한 PyTorch가 운영 driver와 호환되는지 별도로 확인한다.

## CPU Dry-run

모든 CLI 경로는 absolute path여야 한다. 아래 placeholder를 로컬 환경에 맞게
지정한다. Dry-run은 tiny subset으로 mapping, split, head, forward/backward,
metric, progress와 checkpoint save/reload를 검증하며 `dry-run/`에만 기록한다.

```powershell
$repo = (Get-Location).Path
$env:PYTHONPATH = "services"
$trainJson = "C:\path\to\emotional-dialogue\label\Training.json"
$validationJson = "C:\path\to\emotional-dialogue\label\Validation.json"
$tfidfOutput = "C:\path\to\tfidf-baseline"
$coarseOutput = "C:\path\to\transformer-coarse-baseline"
$mapping = Join-Path $repo "services\ai\config\emotion_label_mapping.json"

python services\ai\scripts\train_transformer_baseline.py `
  --train-json $trainJson `
  --validation-json $validationJson `
  --tfidf-output-dir $tfidfOutput `
  --output-dir $coarseOutput `
  --label-level coarse `
  --label-mapping-path $mapping `
  --model-name klue/roberta-base `
  --device cpu `
  --dry-run `
  --dry-run-samples 8
```

Linux/macOS에서는 같은 옵션에 `/path/to/...` absolute path를 사용한다.

```bash
PYTHONPATH=services python services/ai/scripts/train_transformer_baseline.py \
  --train-json /path/to/emotional-dialogue/label/Training.json \
  --validation-json /path/to/emotional-dialogue/label/Validation.json \
  --tfidf-output-dir /path/to/tfidf-baseline \
  --output-dir /path/to/transformer-coarse-baseline \
  --label-level coarse \
  --label-mapping-path "$(pwd)/services/ai/config/emotion_label_mapping.json" \
  --model-name klue/roberta-base --device cpu --dry-run --dry-run-samples 8
```

## Full Training

전체 학습은 자동 검증에서 실행하지 않는다. 검증된 실행은 3 epochs,
max length 128, effective batch size 16을 사용했다. Dry-run 명령에서
`--dry-run`과 `--dry-run-samples`를 제거하고 다음 옵션을 추가한다.

```text
--device cuda
--fp16
--epochs 3
--train-batch-size 8
--eval-batch-size 16
--gradient-accumulation-steps 2
--max-length 128
--learning-rate 2e-5
--early-stopping-patience 2
```

`--disable-progress-bar`는 non-TTY 진행바를 끈다. `--show-gpu-memory`,
`--progress-update-interval N`, `--log-every-n-steps N`으로 출력량을 조절한다.

## Output 및 Inference 호환성

Coarse output은 `model/`, `tokenizer/`, `checkpoints/best/`와 함께 다음 metadata를
생성한다.

- `label_mapping.json`, `mapping_validation.json`, `run_config.json`
- `split_summary.json`, `training_history.json`, `best_validation_metrics.json`
- `test_metrics.json`, `classification_report.json`, `confusion_matrix.json`
- `predictions.jsonl`, `comparison_with_fine_baseline.json`

Model config에는 `num_labels=6`과 고정 `id2label/label2id`가 저장된다. Inference
loader는 분리된 `model/`·`tokenizer/` 및 결합된 `checkpoints/best/`를 지원하며,
mapping 순서와 `max_length=128`이 다르면 startup을 거부한다.

검증된 결과는 best epoch 2, validation macro-F1 0.705701, internal test accuracy
0.678079, macro-F1 0.689142, weighted-F1 0.678451이다. 이 수치는 고정 실험 결과이며
API SLO나 임상적 유효성을 뜻하지 않는다.

## 검증 및 Git 정책

```powershell
$env:PYTHONPATH = "services"
python -m pytest -q
python -m ruff check .
python -m mypy services\ai\src
python -m compileall -q services\ai\src services\ai\tests
```

Dataset, output, predictions, model weights, tokenizer cache와 checkpoints는 Git에
추가하지 않는다. `services/ai/data/outputs/`, `services/ai/**/checkpoints/`,
`*.bin`, `*.safetensors` ignore 규칙을 유지한다.
