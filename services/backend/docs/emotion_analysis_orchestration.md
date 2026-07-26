# Emotion Analysis Orchestration

`POST /api/v1/emotion-analyses` accepts the AI service's typed `hs01`, `hs02`,
and optional `hs03` input for the authenticated user. The Backend reuses one
AI service client per application lifespan and closes only clients it creates.

The request text is sent to the AI service but is not stored, logged, returned,
or included in error details. The persistence row contains only the model
version, predicted emotion, confidence, uncertainty flag, the exact six-class
probability distribution, and timestamps. `input_hash` remains `NULL` because
there is no existing keyed-HMAC setting or utility. AI-only fields such as
`predicted_label_id`, `uncertainty_reason`, `top_predictions`, and `latency_ms`
are not persisted or returned.

The current persistence model has no daily-record provenance foreign key, so
the API does not accept a `daily_record_id` or infer a relationship. Successful
requests stage one append-only emotion result and commit once. AI and database
failures roll back the request session, and no baseline or risk evaluation is
triggered.
