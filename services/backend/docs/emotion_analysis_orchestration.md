# Emotion Analysis Orchestration

`POST /api/v1/emotion-analyses` accepts a required `record_date`, the AI
service's typed `hs01`, `hs02`, and optional `hs03` input for the authenticated
user. The date cannot be in the future in UTC. A Behavioral Daily Record must
exist for that user and date; missing records and records owned by another user
both return `404`.

The Backend validates the date and ownership before the AI call, then ends the
database read transaction while waiting for the downstream response. It reuses
one AI service client per application lifespan and closes only clients it
creates.

The request text is sent to `POST /v2/emotions/classify` but is not stored,
logged, returned, or included in error details. The Backend strictly validates
the v2 response and persists `taxonomy_version`, `model_version`,
`threshold_version`, `predicted_emotion`, nullable adopted `emotion`,
`confidence`, `margin`, `provisional`, `is_uncertain`, and the exact
six-class probability distribution. `input_hash` remains `NULL` because there
is no existing keyed-HMAC setting or utility. AI-only fields such as
`predicted_label_id`, `uncertainty_reason`, `top_predictions`, and `latency_ms`
are not persisted or returned.

Taxonomy v1 and v2 are separate historical meanings. A v1 `상처` row remains
v1 and is never reinterpreted as v2 `무기력`. Existing rows are backfilled only
with facts recoverable from the old storage contract: `taxonomy_version=v1`,
`emotion=predicted_emotion`, `provisional=false`, and null v2 threshold
provenance.

For v2, `predicted_emotion` always preserves model argmax. When confidence or
margin does not satisfy the versioned abstention policy, `emotion` is null and
`provisional` is true. This is a successful analysis with preserved
provenance, not a downstream call failure.

The current persistence model has no daily-record provenance foreign key, so
the API associates the result through the verified user and `record_date`.
Successful requests stage one append-only emotion result and commit once.
Multiple analyses may be stored for the same date; Baseline calculation uses
the latest result for that date. AI and database failures roll back the request
session, and no baseline or risk evaluation is triggered.

Framework validation errors expose only `type`, `loc`, and `msg`. The global
handler omits Pydantic's `input` and `ctx` values from body, query, and path
validation responses.
