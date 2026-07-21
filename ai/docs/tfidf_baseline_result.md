# Leakage-safe TF-IDF Baseline

## Dataset policy

- Prediction label: `profile.emotion.type`
- Input fields: HS01, HS02, optional HS03
- Excluded fields: SS01–SS03, emotion-id, situation, profile identifiers
- The original dataset is not included in Git.

## Split policy

- Profile-isolated Train/Validation/Test split
- Profile overlap: 0
- Conversation-key overlap: 0
- Normalized-text overlap: 0
- Approximate split ratio: 80/10/10
- The internal validation split is missing class `E54`.
- Official Validation is reference-only because profile and raw talk-id reuse can
  inflate its score.

## Results

### Internal validation

| Metric | Value |
|---|---:|
| Selected model | char_tfidf |
| Accuracy | 0.367240 |
| Macro-F1 | 0.345950 |
| Weighted-F1 | 0.374615 |

### Internal test

| Metric | Value |
|---|---:|
| Accuracy | 0.333624 |
| Macro-F1 | 0.317472 |
| Weighted-F1 | 0.342856 |

### Official Validation reference

| Metric | Value |
|---|---:|
| Accuracy | 0.518373 |
| Macro-F1 | 0.505518 |
| Weighted-F1 | 0.517117 |

## Interpretation

- Character TF-IDF outperformed word TF-IDF in internal validation.
- Internal Test is the primary generalization baseline.
- Official Validation is not leakage-safe performance and must not be used as
  final generalization evidence.
- This classifier is not a medical diagnostic model. Re:Mind uses emotion
  signals only as one input for burnout-risk support.
