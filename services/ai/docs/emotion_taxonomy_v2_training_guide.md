# Re:Mind 감정 대분류 v2 학습 가이드

## 범위

이 경로는 다음 새 단일 라벨 분류 실험을 위한 학습 전용 경로다.

```text
분노 / 기쁨 / 불안 / 당황 / 슬픔 / 무기력
```

현재 운영 중인 `official-coarse-v1`의 `상처`를 이름만 바꾸지 않는다.
원본 fine label `E25(마비된)`와 `E28(낙담한)`을 `무기력`으로
결정적으로 재매핑하고,
기존 `상처` 계열 `E40~E49`는 v2 준비 데이터에서 제외한다.

최종 모델을 선정하기 전에는 공유 inference 계약, 백엔드 enum, DB 제약을
변경하지 않는다. 기존 운영 모델과 저장 이력은 여전히 v1 의미를 가진다.

## 라벨 판정 기준

| 라벨 | 중심 의미 |
|---|---|
| 분노 | 분노, 짜증, 적개심, 강한 불쾌감 |
| 기쁨 | 기쁨, 만족, 감사, 안도, 긍정적 기대 |
| 불안 | 걱정, 두려움, 긴장, 통제하기 어려운 염려 |
| 당황 | 당혹감, 혼란, 놀람, 수치심, 난처함 |
| 슬픔 | 상실, 비통함, 우울감, 낙담 |
| 무기력 | 의욕 저하, 에너지 고갈, 시작 회피, 행동 지속의 어려움 |

`피곤하다`만으로는 무기력으로 판정하지 않는다. 수면 부족이나 신체 피로가
있더라도 행동 의욕·시작 능력 저하가 문장의 중심인지 확인한다. 슬픔과
무기력이 함께 나타나면 대표 라벨을 하나 선택해야 한다.

- 상실감과 비통함이 중심이면 `슬픔`
- 시작할 힘이 없고 아무것도 하기 싫다는 상태가 중심이면 `무기력`
- `E25` 내부 오류 사례는 최종 모델 선정 전 별도의 오류 분석에서 검수한다

## 원본 fine label 재그룹화 정책

공식 60개 fine label을 다음처럼 고정 매핑한다.

```text
E10~E19               → 분노
E20~E24, E26~E27, E29 → 슬픔
E25, E28               → 무기력
E30~E39               → 불안
E40~E49               → 제외
E50~E59               → 당황
E60~E69               → 기쁨
```

이 정책은 `services/ai/config/emotion_label_policy_v2.json`이 단일 기준이다.
문장별 CSV 검수 결과는 기본 학습 입력으로 사용하지 않는다. 정책을 바꾸는
실험은 policy version과 출력 디렉터리를 새로 만들고, 이전 internal test를
최종 holdout으로 재사용하지 않는다.

`dataset_release_id`는 사용한 로컬 원본 릴리스를 나타내는 비민감 식별자다.
파일 경로나 사용자 식별자를 넣지 않고 영문자·숫자로 시작하며 영문자, 숫자,
`.`, `_`, `-`만 사용하는 최대 64자의 opaque ID를 명령행으로 전달한다.

## 공통 split 정책

v2 overlay와 제외 처리를 먼저 적용한 뒤 profile-safe split을 만든다.
TF-IDF가 만든 다음 파일을 Transformer가 그대로 검증하고 사용한다.

```text
<tfidf-output>/private/split_assignment.json
```

이 파일에는 exact membership 검증을 위한 `profile_id`, `talk_id`와 텍스트
digest가 들어 있으므로 외부에 공유하거나 모델 패키지에 포함하면 안 된다.
공유 가능한 JSON에는 집계 분포와 검증 여부만 기록된다.

v2 split은 다음 조건을 모두 만족해야 한다.

- train, validation, test 사이 profile 중복 0
- conversation key 중복 0
- 정규화된 동일 문장 중복 0
- 세 split 모두 6개 클래스 포함
- 클래스마다 최소 3개의 서로 다른 profile 보유

## 환경 준비

저장소 루트에서 실행한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r services\ai\requirements-dev.txt
python -m pip install -r services\ai\requirements-transformer.txt
$env:PYTHONPATH = "services"

python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

경로 변수 예시:

```powershell
$repo = (Get-Location).Path
$trainJson = "C:\path\to\emotional-dialogue\label\Training.json"
$validationJson = "C:\path\to\emotional-dialogue\label\Validation.json"
$datasetReleaseId = "aihub-emotional-dialogue-local-r1"
$tfidfV2Output = "C:\remind-models\tfidf-remind-coarse-v2"
$transformerV2Output = "C:\remind-models\klue-roberta-remind-coarse-v2"
```

## TF-IDF 학습

```powershell
python services\ai\scripts\train_tfidf_baseline.py `
  --train-json $trainJson `
  --validation-json $validationJson `
  --output-dir $tfidfV2Output `
  --label-set remind-coarse-v2 `
  --dataset-release-id $datasetReleaseId `
  --include-combined
```

TF-IDF는 validation macro-F1으로 word/char/combined 후보 중 하나를 고르고,
선택이 끝난 다음 internal test를 한 번 평가한다.

## Transformer CPU dry-run

```powershell
python services\ai\scripts\train_transformer_baseline.py `
  --train-json $trainJson `
  --validation-json $validationJson `
  --dataset-release-id $datasetReleaseId `
  --tfidf-output-dir $tfidfV2Output `
  --output-dir $transformerV2Output `
  --label-level coarse-v2 `
  --model-name klue/roberta-base `
  --device cpu `
  --dry-run `
  --dry-run-samples 12 `
  --disable-progress-bar
```

dry-run은 v2 준비, exact split 재사용, 6-class head, balanced loss,
forward/backward, 임시 checkpoint 저장·재로드까지만 확인한다. 최종 test
평가나 배포 모델 저장은 수행하지 않는다.

## Transformer GPU full training

```powershell
python services\ai\scripts\train_transformer_baseline.py `
  --train-json $trainJson `
  --validation-json $validationJson `
  --dataset-release-id $datasetReleaseId `
  --tfidf-output-dir $tfidfV2Output `
  --output-dir $transformerV2Output `
  --label-level coarse-v2 `
  --model-name klue/roberta-base `
  --device cuda `
  --fp16 `
  --epochs 3 `
  --train-batch-size 8 `
  --eval-batch-size 16 `
  --gradient-accumulation-steps 2 `
  --max-length 128 `
  --learning-rate 2e-5 `
  --early-stopping-patience 2 `
  --class-weighting balanced `
  --benchmark-warmup-runs 3 `
  --benchmark-runs 20 `
  --num-workers 0 `
  --show-gpu-memory
```

split random state는 TF-IDF artifact에서 읽고, Transformer의
`--random-state`는 학습 seed로만 사용한다.

중단된 full training을 재개할 때는 원래 명령의 데이터, dataset release ID,
base model, label 순서, split, 학습 seed와 하이퍼파라미터를 그대로 유지하고
`--resume-from-checkpoint <output>\checkpoints\last`만 추가한다. checkpoint에는
이 값을 묶은 provenance와 exact split fingerprint가 저장되며 하나라도 다르면
재개를 거부한다. `best` checkpoint도 같은 `checkpoints` 디렉터리에 보존되어야
하며, dry-run에서는 resume을 허용하지 않는다. `--model-name`은 경로가 아니라
`klue/roberta-base` 같은 공개 Hugging Face model ID만 허용한다.

## 결과 확인

두 모델은 동일한 표본·라벨 순서·split으로 비교된다. 주 지표는
validation macro-F1이며 test는 모델 선택이 고정된 후 한 번만 평가한다.

주요 결과물:

```text
label_classes.json
label_policy_summary.json
preparation_report.json
run_config.json
model_metadata.json
validation_metrics.json
test_metrics.json
classification_report.json
confusion_matrix.json
evaluation_summary.json
training_summary.json 또는 training_history.json
inference_benchmark.json
comparison.json
```

`run_config.json`과 `model_metadata.json`의 `run_fingerprint`는 같은 고정 실험을
식별한다. 고정 `model_version`만으로 서로 다른 데이터 revision이나 학습 run을
같은 artifact로 간주하면 안 된다.

`evaluation_summary.json`에는 validation/test macro-F1 차이와 train support가
가장 작은 클래스의 test precision/recall/F1이 기록된다.
`inference_benchmark.json`에는 batch 1/8/32의 warm-up 제외 p50/p95 latency와
throughput이 기록된다. 원문이나 source ID는 포함되지 않는다.

집계 JSON과 Markdown 보고서가 안전 검사를 통과했다는 사실이 모델 파일 전체를
외부 공유해도 된다는 뜻은 아니다. 특히 TF-IDF의 `vectorizer.joblib`에는 원본에서
학습한 vocabulary와 n-gram이 들어 있으므로 로컬 모델 산출물로 취급하고, 데이터
라이선스·보안 검토 없이 배포 패키지에 포함하지 않는다. `private/` 디렉터리는
항상 패키징 대상에서 제외한다.

Transformer 출력의 `comparison.json`은 다음 동일성을 먼저 검증한다.

- taxonomy: `remind-coarse-v2`
- ordered labels
- `dataset_release_id`
- deterministic fine-label policy
- exact private split membership

이 검증이 모두 통과한 경우에만 TF-IDF와 Transformer 결과를 같은 실험으로
비교할 수 있다.

## 모델 선정 이후

GPU full training과 오류 분석으로 최종 모델을 선정한 다음 별도 통합 변경에서:

1. v2 confidence threshold와 top-2 margin을 validation에서 보정
2. `taxonomy_version`과 `model_version`을 inference 응답에 고정
3. 공유 계약과 백엔드가 v1 이력과 v2 결과를 구분하도록 확장
4. 기존 `상처` 저장 행을 `무기력`으로 변환하지 않고 v1 이력으로 보존
5. 행동-only와 행동+감정 Risk 결과를 비교한 뒤 감정 영향력을 확정

한다.
