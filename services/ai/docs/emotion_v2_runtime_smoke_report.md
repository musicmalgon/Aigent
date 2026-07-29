# Emotion v2 Runtime Smoke Report

## Scope

- 실행일: 2026-07-29
- endpoint: `POST /v2/emotions/classify`
- label schema: `remind-coarse-v2`
- model: `klue-roberta-remind-coarse-v2-e25e28`
- artifact: `C:\remind-models\klue-roberta-remind-coarse-v2-e25e28`
- 입력: 원시 학습 데이터와 무관한 합성 서비스 문장 24건
- 설정: `confidence_threshold=0.45`, `margin_threshold=0.10`

이 결과는 작은 합성 스모크 테스트이며 validation/test 성능 지표가 아니다.
이 실행에서 확인한 경계 문제를 반영해 이후 runtime 기본값은
`confidence_threshold=0.65`, `margin_threshold=0.15`,
`threshold_version=mvp-v1`로 변경했다.

## Summary

- 명확한 6개 감정 예시: 18건
- 사전 의도와 top-1 방향이 일치한 예시: 15건
- 명확한 감정 예시 중 uncertain: 3건
- 전체 uncertain: 5건
- 후속 24건 평균 latency: 42.0 ms
- 후속 24건 중앙 latency: 49.5 ms
- 별도 첫 warm request latency: 369.8 ms

## Results

| ID | 의도 | top-1 | confidence | top-2 | margin | uncertain |
|---|---|---:|---:|---:|---:|---|
| anger-1 | 분노 | 분노 | 0.970 | 당황 | 0.959 | false |
| anger-2 | 분노 | 분노 | 0.922 | 슬픔 | 0.876 | false |
| anger-3 | 분노 | 분노 | 0.964 | 불안 | 0.950 | false |
| joy-1 | 기쁨 | 기쁨 | 0.997 | 슬픔 | 0.996 | false |
| joy-2 | 기쁨 | 기쁨 | 0.997 | 불안 | 0.996 | false |
| joy-3 | 기쁨 | 기쁨 | 0.997 | 불안 | 0.996 | false |
| anxiety-1 | 불안 | 불안 | 0.897 | 분노 | 0.847 | false |
| anxiety-2 | 불안 | 불안 | 0.967 | 분노 | 0.952 | false |
| anxiety-3 | 불안 | 불안 | 0.918 | 분노 | 0.856 | false |
| embarrassment-1 | 당황 | 당황 | 0.904 | 불안 | 0.826 | false |
| embarrassment-2 | 당황 | 당황 | 0.444 | 불안 | 0.168 | true |
| embarrassment-3 | 당황 | 무기력 | 0.952 | 불안 | 0.938 | false |
| sadness-1 | 슬픔 | 슬픔 | 0.951 | 무기력 | 0.923 | false |
| sadness-2 | 슬픔 | 슬픔 | 0.343 | 당황 | 0.084 | true |
| sadness-3 | 슬픔 | 무기력 | 0.732 | 슬픔 | 0.517 | false |
| lethargy-1 | 무기력 | 무기력 | 0.378 | 불안 | 0.032 | true |
| lethargy-2 | 무기력 | 불안 | 0.515 | 무기력 | 0.237 | false |
| lethargy-3 | 무기력 | 무기력 | 0.957 | 슬픔 | 0.939 | false |
| neutral-1 | 중립 | 기쁨 | 0.872 | 불안 | 0.815 | false |
| neutral-2 | 중립 | 기쁨 | 0.389 | 분노 | 0.092 | true |
| mixed-1 | 복합 | 불안 | 0.930 | 기쁨 | 0.897 | false |
| mixed-2 | 복합 | 불안 | 0.932 | 분노 | 0.886 | false |
| short-1 | 애매 | 무기력 | 0.321 | 불안 | 0.054 | true |
| emoji-1 | 애매 | 기쁨 | 0.997 | 무기력 | 0.996 | false |

## Important Observations

1. 명확한 분노·기쁨·불안 문장은 안정적으로 분리됐다.
2. `파일이 사라져 머리가 하얘졌다`는 당황 문장을 무기력으로 매우 확신했다.
3. `기회를 놓쳐 속상하다`는 슬픔 문장을 무기력으로 분류했다.
4. 일부 무기력 문장은 불안과 가깝게 나타났다.
5. 중립 클래스가 없으므로 감정 표현이 없는 일상 기록도 여섯 클래스 중 하나로
   강제된다. 이 결과를 그대로 Risk 신호로 사용하면 안 된다.
6. 현재 `0.45/0.10` 기준에서는 confidence `0.515`의 오분류가 uncertain이
   아니다. 제품 적용 전 validation 기반 threshold 보정이 필요하다.

## Applied MVP Product Gate

정식 calibration 전 임시 보수 정책으로 다음을 적용한다.

```text
confidence >= 0.65
and top1 - top2 >= 0.15
→ 예측 감정을 보조 신호로 사용

그 외
→ provisional=true
→ Risk Engine의 감정 영향 제외 또는 감쇠
```

이 임시값을 최종 모델 임곗값으로 주장해서는 안 된다. validation prediction을
사용해 coverage와 오류율의 trade-off를 먼저 계산해야 한다.

## Applied Gate Verification

서버 재시작 후 `mvp-v1` 정책의 양쪽 경로를 실제 GPU inference로 확인했다.

### Abstained

```json
{
  "taxonomy_version": "v2",
  "threshold_version": "mvp-v1",
  "predicted_emotion": "불안",
  "emotion": null,
  "confidence": 0.40346571803092957,
  "margin": 0.031515300273895264,
  "provisional": true,
  "is_uncertain": true,
  "uncertainty_reason": "low_confidence_and_small_margin"
}
```

### Accepted

```json
{
  "taxonomy_version": "v2",
  "threshold_version": "mvp-v1",
  "predicted_emotion": "기쁨",
  "emotion": "기쁨",
  "confidence": 0.9966291785240173,
  "margin": 0.9957887216005474,
  "provisional": false,
  "is_uncertain": false,
  "uncertainty_reason": null
}
```
