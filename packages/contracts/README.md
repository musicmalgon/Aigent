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
