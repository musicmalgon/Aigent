# Shared Contracts

JSON Schema files in `schemas/` are the repository-level source of truth for
service boundaries. Python Pydantic models mirror these schemas and contract
tests check that required fields, labels, examples, and nullability remain in
sync.

The existing `emotion_analysis.schema.json` contract remains the legacy
four-label (`stable`, `fatigue`, `anxiety`, `other`) application contract.
Six-class model inference uses two additive contracts:

- `coarse_emotion_inference_request.schema.json`
- `coarse_emotion_inference_response.schema.json`

The independently versioned Re:Mind v2 taxonomy uses:

- `remind_coarse_emotion_inference_request.schema.json`
- `remind_coarse_emotion_inference_response.schema.json`

Its fixed model-index order is `분노`, `기쁨`, `불안`, `당황`, `슬픔`,
`무기력`, and every response includes
`taxonomy_version=v2`. The v1 contracts below remain frozen
for existing persistence history.

The six coarse labels have a fixed model-index order:

1. `기쁨`
2. `불안`
3. `당황`
4. `분노`
5. `슬픔`
6. `상처`

Changing this order is a model compatibility change. Do not infer it from
alphabetical ordering or from the legacy four-label adapter.

JSON Schema enforces field shape, exact probability keys, label/id mapping,
and uncertainty nullability. Probability sum, argmax/confidence equality, and
top-prediction ordering are arithmetic cross-field invariants that JSON Schema
cannot express; service runtime models must enforce them before serialization.

The deterministic backend risk engine adds:

- `burnout_risk_evaluation_request.schema.json`
- `burnout_risk_evaluation_response.schema.json`

These contracts use the existing `snake_case` behavioral metric names. The
result is a versioned, non-diagnostic signal with explainable factor codes; it
does not contain raw user text or a medical interpretation.
