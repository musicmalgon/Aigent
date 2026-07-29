# Six-class Coarse Emotion Inference

## Scope

This service exposes the selected Re:Mind v2 Transformer as a separate,
versioned inference boundary. It does not rewrite the existing v1 `상처`
history or the four-label `EmotionAnalysis` schema. The output is a model
estimate, not a medical diagnosis or treatment recommendation.

Fixed model-index order:

| id | label |
|---:|---|
| 0 | 분노 |
| 1 | 기쁨 |
| 2 | 불안 |
| 3 | 당황 |
| 4 | 슬픔 |
| 5 | 무기력 |

## Validated Baseline

The external artifact was validated with the following saved results:

- best epoch: 2
- best validation macro-F1: 0.705701
- internal test accuracy: 0.678079
- internal test macro-F1: 0.689142
- internal test weighted-F1: 0.678451

These figures describe the frozen experiment artifact. They are not API SLOs,
production accuracy guarantees, or evidence of clinical validity. Internal test
data must not be rerun during model selection or routine integration checks.

## Artifact Layouts

Model files are not committed. Configure one of these local layouts:

```text
artifact-root/
  model/                 # config.json and model weights
  tokenizer/             # tokenizer files
  label_classes.json     # v2 ordered classes and label/id maps
  run_config.json        # v2 experiment metadata
```

```text
artifact-root/
  checkpoints/best/      # combined model and tokenizer
  label_classes.json
```

Explicit model and tokenizer directories are also supported. Startup rejects
missing weights/tokenizer files, a 60-class/fine mapping, non-six-label config,
or any label order different from the table above. Transformers loads with
`local_files_only=True`.

## Configuration

Copy values from `.env.example` into the process environment. Important keys:

- `EMOTION_ARTIFACT_DIR`: artifact root for automatic layout discovery
- `EMOTION_MODEL_DIR`, `EMOTION_TOKENIZER_DIR`: explicit path overrides
- `EMOTION_LABEL_MAPPING_PATH`: optional legacy explicit metadata override;
  normal v2 artifact discovery uses `label_classes.json`
- `EMOTION_DEVICE`: `auto`, `cpu`, `cuda`, or `mps`
- `EMOTION_MAX_LENGTH`: fixed to the training value `128`; any other value fails
  startup validation
- `EMOTION_CONFIDENCE_THRESHOLD`: MVP abstention threshold, defaults to `0.65`
- `EMOTION_MARGIN_THRESHOLD`: top-one/top-two margin threshold, defaults to
  `0.15`
- `EMOTION_THRESHOLD_VERSION`: provenance for the applied abstention policy,
  defaults to `mvp-v1`
- `EMOTION_MODEL_VERSION`: response/log version, defaults to
  `klue-roberta-remind-coarse-v2`
- `EMOTION_TOP_K`: ranked predictions returned, defaults to `2`

`auto` prefers CUDA, then MPS, then CPU. An explicitly requested unavailable
accelerator fails readiness instead of silently changing devices.

## Input Parity

`hs01` and `hs02` are required; `hs03` is optional. The inference path reuses
the training normalizer, joins present turns in order with the loaded
tokenizer's actual separator token, and tokenizes with truncation and maximum
length 128. Empty required turns and inputs longer than 2,000 characters per
turn are rejected before inference. Every tensor returned by the tokenizer,
including `attention_mask`, is moved to the selected device and passed through.
The adapter does not synthesize `token_type_ids` when the tokenizer does not
return them.

## API

From the repository root on Windows PowerShell:

```powershell
$env:PYTHONPATH = "services"
$env:EMOTION_ARTIFACT_DIR = "C:\path\to\transformer-coarse-baseline"
python -m uvicorn ai.src.main:app --host 127.0.0.1 --port 8001
```

Linux/macOS:

```bash
PYTHONPATH=services \
EMOTION_ARTIFACT_DIR=/path/to/transformer-coarse-baseline \
python -m uvicorn ai.src.main:app --host 127.0.0.1 --port 8001
```

Endpoints:

- `GET /health/live`: process liveness
- `GET /health/ready`: model/tokenizer readiness, `503` until loaded
- `POST /v2/emotions/classify`: one three-turn conversation

Example request:

```json
{"hs01":"오늘 프로젝트를 마쳤어.","hs02":"후련하고 기분이 좋아.","hs03":null}
```

The response preserves the raw `predicted_emotion` and label id, and separately
returns nullable `emotion` for product use. `emotion` is null and
`provisional=true` unless both configured thresholds pass. It also includes
the top-one/top-two `margin`, `threshold_version`, all six probabilities,
ranked top predictions, model version, and latency.
Probabilities are normalized and keyed by the fixed labels above.

`is_uncertain` and `provisional` are true when confidence is below the
configured threshold, the top-two probability margin is below its threshold,
or both. Downstream Risk evaluation must ignore the emotion signal when
`emotion` is null; it must not convert the raw prediction into an accepted
emotion.

The model and tokenizer load once during application lifespan. Inference is
serialized for thread safety, batches are supported by the analyzer, and CUDA
out-of-memory is returned as a typed service error. Logs contain model/device,
batch size, status, and latency but never raw conversation text.

## Verification

```powershell
python -m pytest -q services\ai\tests -p no:cacheprovider
python -m ruff check services\ai\src services\ai\tests
python -m mypy services\ai\src
python -m compileall -q services\ai\src services\ai\tests
```

Unit/API tests use fake model components and synthetic text. A release smoke
test may load the real artifact and run a few synthetic requests, but it must
not evaluate the saved internal test split again.

The backend owns authentication, persistence, request timestamps, and product
policy. The AI service owns model loading, preprocessing, inference,
probabilities, uncertainty metadata, and model version. Persist the complete
probability distribution plus model version when product requirements call for
auditability.
