# KLUE-RoBERTa Transformer baseline 가이드

## 목적과 기준선 관계

이 구현은 `emotion.type` 다중 클래스 분류에서 TF-IDF 다음 단계의 로컬
baseline을 제공한다. 기본 모델은 `klue/roberta-base`이며 주 평가지표는
internal test macro-F1이다. TF-IDF의 leakage-safe internal test macro-F1을
비교 기준으로 읽되, Transformer 성능은 실제 로컬 학습 전에는 기록하지 않는다.

이 분류 결과는 실험용 감정 신호이며 의료적 진단, 확률 또는 치료 판단이 아니다.

## 데이터 정책

- JSON 루트 레코드 배열만 사용한다.
- 라벨은 `$.profile.emotion.type`만 사용한다.
- 입력은 `HS01`, `HS02`, 선택적인 비어 있지 않은 `HS03`만 사용한다.
- 각 발화는 tokenizer의 `sep_token`으로 연결한다.
- `SS01`~`SS03`, `emotion-id`, `situation`, persona와 기타 metadata는 제외한다.
- `profile-id`, `talk-id`, `(profile-id, talk-id)`는 split 검증에만 쓰고 모델
  feature로 전달하지 않는다.
- 원본 JSON, 원문, ID, 개별 예측, hash/digest, 모델 산출물은 커밋하지 않는다.

## TF-IDF split 재사용과 누수 검증

Transformer는 새 split을 만들지 않는다. TF-IDF 출력의 안전한 `run_config.json`
에서 `random_state`와 후보 수를 읽고, 공식 Training 다음 Validation 순서로
결합한 데이터에 동일한 `select_group_safe_split`을 다시 실행한다. 재현된
레코드 수, profile 수, 클래스 분포, 누락 클래스와 candidate seed가 TF-IDF의
`split_summary.json`과 다르면 학습 전에 실패한다. 인덱스 manifest는 저장하지
않으므로 데이터 순서나 길이가 바뀌어도 안전하게 거부된다.

학습 전 필수 검사는 다음과 같다.

- split 간 profile-id overlap 0
- split 간 `(profile-id, talk-id)` conversation-key overlap 0
- split 간 정규화 사용자 텍스트 overlap 0
- internal train에 전체 `emotion.type` 클래스 존재

raw talk-id는 전역 고유 ID가 아니므로 overlap을 참고 통계로만 유지한다.
validation/test의 누락 클래스는 허용하고 split summary에 기록한다.

## 모델과 학습 기본값

- `AutoTokenizer`, `AutoModelForSequenceClassification`
- sorted class order와 명시적인 `label2id`/`id2label`
- 최대 길이 128, truncation, `DataCollatorWithPadding` 동적 padding
- 3 epochs, learning rate `2e-5`, weight decay `0.01`, warmup ratio `0.1`
- train batch 8, gradient accumulation 2, effective batch 16
- eval batch 16, gradient clipping `1.0`, seed 42, workers 0
- validation macro-F1 기준 best checkpoint, early stopping patience 2

custom PyTorch loop가 매 epoch internal validation을 평가한다. internal test와
official Validation은 best model 확정 뒤 각각 한 번만 평가한다. 같은 output
directory에 완료 state가 있으면 반복 평가를 거부하며, 의도적인 재평가는
`--force-evaluate`가 필요하다. official Validation은 알려진 group overlap 때문에
참고값이며 최종 일반화 성능으로 표현하지 않는다.

## Device와 MPS 주의사항

`--device auto`는 CUDA, MPS, CPU 순으로 선택한다. 명시한 accelerator가 없으면
기본적으로 실패하며 `--allow-cpu-fallback`을 준 경우에만 CPU로 전환한다. CUDA는
사용 가능 여부를 확인하지만 이 baseline은 재현성과 장치 간 일관성을 위해
mixed precision을 기본 활성화하지 않는다. CUDA에서만 명시적인 `--fp16`을
지원하며 MPS와 CPU에서는 안전하게 거부한다.

Apple Silicon의 MPS는 모든 연산을 지원하지 않을 수 있고 전체 모델이 unified
memory에 들어가야 한다. 오류가 나면 먼저 batch size 또는 `max_length`를 줄인다.
필요한 경우 사용자가 명시적으로 `PYTORCH_ENABLE_MPS_FALLBACK=1`을 설정할 수
있지만, CPU fallback 연산으로 속도와 재현 특성이 달라질 수 있으므로 run 기록에
남겨야 한다.

현재 macOS용 PyTorch 공식 안내는 Python 3.9~3.12를 권장한다. Python 3.13
환경에서 설치가 실패하면 기존 환경을 억지로 변경하지 말고 별도의 Python 3.12
가상환경을 만든다. 이 저장소는 특정 hardware wheel을 고정하지 않는다.

## 설치와 dry-run

저장소 밖의 전용 가상환경을 활성화한 뒤 선택 의존성을 설치한다.

```bash
python -m pip install -r ai/requirements-dev.txt
python -m pip install -r ai/requirements-transformer.txt
```

먼저 dry-run으로 schema, split 재현, overlap, 라벨 인코딩, tokenizer, 작은 batch,
model forward, metric 경로만 확인한다. 전체 학습과 final test 평가는 하지 않는다.

```bash
python ai/scripts/train_transformer_baseline.py \
  --train-json /absolute/path/to/Training.json \
  --validation-json /absolute/path/to/Validation.json \
  --tfidf-output-dir /absolute/path/to/tfidf-output \
  --output-dir /absolute/path/to/transformer-output \
  --model-name klue/roberta-base \
  --device mps \
  --max-length 128 \
  --epochs 3 \
  --train-batch-size 8 \
  --eval-batch-size 16 \
  --gradient-accumulation-steps 2 \
  --dry-run \
  --dry-run-samples 32
```

성공 후 `--dry-run`과 `--dry-run-samples`만 제거하여 전체 학습한다. 최초 실행은
Hugging Face model/tokenizer를 사용자 cache에 내려받을 수 있다. 모델 다운로드와
대용량 학습은 Codex가 대신 실행하지 않는다.

중단 뒤 이어서 학습할 때는 이 스크립트가 만든 `checkpoints/last` 또는
`checkpoints/interrupted`의 절대경로를 `--resume-from-checkpoint`로 지정한다.
model weight뿐 아니라 optimizer, scheduler, epoch와 early-stopping state도
복원한다. 일반 Hugging Face model directory처럼 trainer state가 없는 경로는
resume 대상으로 거부한다.

## 산출물과 해석

전체 학습은 `model/`, `tokenizer/`, `checkpoints/`, `validation_metrics.json`,
`test_metrics.json`, `official_validation_metrics.json`, `run_config.json`,
`label_classes.json`, `split_summary.json`, `training_history.json`,
`comparison.json`, `evaluation_state.json`, `README.md`를 output directory에 만든다.
dry-run은 모델이나 평가 점수 대신 `dry_run_summary.json`을 만든다.

`comparison.json`은 internal test끼리만 absolute/relative macro-F1 변화를 계산한다.
0으로 나누는 경우 relative improvement는 `null`이다. confusion matrix와
클래스별 지표는 aggregate이며 record-level 결과는 저장하지 않는다.

재현성은 고정 seed, 결정적인 group split, train-only fitting, stable label order로
관리한다. 장치 kernel과 라이브러리 버전에 따라 bitwise 동일성은 보장되지 않는다.

## 개인정보·라이선스 안전

원본 데이터 사용 조건과 KLUE-RoBERTa 모델 라이선스를 사용자가 학습 전에 직접
확인해야 한다. output directory와 Hugging Face cache, checkpoint, model weight는
Git에서 제외한다. 오류 메시지와 JSON 결과에는 입력 절대경로, 실제 원문, 실제 ID,
hash 또는 digest를 넣지 않는다.
