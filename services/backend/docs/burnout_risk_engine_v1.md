# Burnout Risk Engine v1

## Purpose and scope

`burnout-risk-rules-v1` is a deterministic product-policy signal calculator.
It compares recent lifestyle and coarse-emotion observations with a personal
baseline and returns a score from 0 to 100 with auditable factors.

The result is not a medical diagnosis, disease probability, treatment
recommendation, or crisis assessment. No LLM calculates, changes, or explains
the score. The v1 package performs no authentication, database access, network
request, AI inference, notification, or persistence. An API may reuse the same
models later, but no endpoint is included in this change.

## Input

Input field names follow the shared behavioral contracts. The current signal
supports:

- sleep, work/study, rest, and exercise minutes
- schedule count
- subjective stress and fatigue from 0 to 10
- all six coarse-emotion probabilities
- optional emotion confidence and uncertainty

The six emotions are `기쁨`, `불안`, `당황`, `분노`, `슬픔`, and `상처`.
Their probabilities must each be between 0 and 1 and sum to 1. Missing values
are omitted or `null`; an observed zero is not missing.

## Personal baseline

The baseline stores matching lifestyle averages, subjective averages,
`negative_emotion_probability`, and `sample_days`. A baseline is:

- `ready` at 7 or more sample days
- `insufficient` at fewer than 7 sample days
- `missing` when absent

Seven days is a minimum calculation rule, not a recommended learning window.
A production service should normally collect 2 to 4 weeks before treating a
personal baseline as stable.

When a ready baseline lacks the matching field, that signal uses a weak
absolute fallback and makes the result provisional. A zero baseline never
causes division by zero.

## Categories and weights

The configured category weights sum to 1:

| Category | Weight |
| --- | ---: |
| sleep | 0.25 |
| workload | 0.20 |
| recovery | 0.20 |
| emotion | 0.20 |
| subjective | 0.15 |

Only available categories participate. Their weights are renormalized, so a
missing category is not treated as normal or as zero risk. Data quality is
`sufficient` when at least 4 of 7 signal groups and at least 3 categories are
available.

Sleep uses personal-baseline decline:

- 0 to 10% decline maps from 0.0 to 0.2 severity
- 10 to 25% maps from 0.2 to 0.6
- 25 to less than 40% maps from 0.6 to 0.9
- 40% or more maps to 1.0

An increase in sleep does not add risk. Work/study and schedule increases use
65% and 35% internal weights. Rest and exercise declines use 80% and 20%.
Exercise severity is capped at 0.30 so one zero-exercise day cannot produce a
high result by itself.

Subjective stress and fatigue use 55% and 45% internal weights. With a ready
matching baseline, only an increase contributes. Subjective severity is capped
at 0.45 so this self-report category cannot produce a high result by itself.

## Emotion policy

The engine uses the full distribution rather than only the top label:

```text
negative_emotion_probability =
  P(불안) + P(당황) + P(분노) + P(슬픔) + P(상처)
```

With a ready emotion baseline, only the increase contributes. Without one,
current negative mass is a weak fallback capped at 0.50 severity.

Confidence applies a multiplier from 0.50 to 1.00. Missing confidence uses
0.75. `emotion_uncertain=true` applies an additional 0.75 multiplier. These
values are versioned policy assumptions, not validated clinical coefficients.

## Missing data and provisional results

A result is provisional when:

- the baseline is missing or insufficient
- a used signal lacks its matching ready-baseline value
- data quality is insufficient

Absolute fallback rules are deliberately capped. All provisional results are
capped at 74.99, so v1 never reports `very_high` from provisional evidence.
Informational factors `insufficient_baseline` and `insufficient_data` explain
limitations with zero score contribution.

## Score, levels, and factors

Category severity is multiplied by its renormalized category weight. Positive
factor contributions sum to the final score.

- `low`: 0 to less than 25
- `moderate`: 25 to less than 50
- `high`: 50 to less than 75
- `very_high`: 75 to 100

Factors are sorted by contribution descending and include a stable `code`,
`message_key`, observed value, baseline value, change, severity, applied
weight, and contribution. Raw user text and diagnostic wording are never
included.

Changing any weight, breakpoint, fallback, confidence adjustment, or cap
requires a new `engine_version`; policy must not silently change under
`burnout-risk-rules-v1`.

## Example

```python
from backend.app.domain.risk import (
    BurnoutRiskEngine,
    CurrentRiskSignals,
    EmotionProbabilities,
    PersonalBaseline,
)

current = CurrentRiskSignals(
    sleep_minutes=270,
    work_or_study_minutes=540,
    rest_minutes=20,
    exercise_minutes=0,
    schedule_count=6,
    subjective_stress=8,
    subjective_fatigue=7,
    emotion_probabilities=EmotionProbabilities(
        **{
            "기쁨": 0.03,
            "불안": 0.42,
            "당황": 0.11,
            "분노": 0.08,
            "슬픔": 0.25,
            "상처": 0.11,
        }
    ),
    emotion_confidence=0.42,
    emotion_uncertain=True,
)
baseline = PersonalBaseline(
    sleep_minutes=420,
    work_or_study_minutes=300,
    rest_minutes=90,
    exercise_minutes=25,
    schedule_count=3,
    subjective_stress=4,
    subjective_fatigue=3,
    negative_emotion_probability=0.38,
    sample_days=18,
)

result = BurnoutRiskEngine().evaluate(current=current, baseline=baseline)
```

## Known limitations and calibration

- v1 evaluates one prepared observation; it does not aggregate 7- or 14-day
  trends.
- It does not build or persist a personal baseline.
- Emotion inference must be supplied by a caller.
- Product weights and breakpoints are explainable hypotheses, not clinically
  validated thresholds.
- Real use requires calibration, fairness review, and repeatability analysis on
  consented user data.
- Crisis-language handling belongs to a separate safety workflow and must never
  be replaced by this score.

For an academic presentation, the evolution is: static explainable rules,
factor audit trail, personal-baseline comparison, then calibration with real
usage data.
