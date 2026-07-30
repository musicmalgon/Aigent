# Recovery Report API

The Recovery Report API turns one stored Risk Evaluation into a seven-day,
non-diagnostic lifestyle report.

## Endpoints

```text
POST /api/v1/recovery-reports
GET  /api/v1/recovery-reports/latest
GET  /api/v1/recovery-reports
```

POST accepts only:

```json
{
  "risk_evaluation_id": "..."
}
```

The authenticated user id is never accepted from the request body. A missing
or another user's Risk Evaluation is returned as the same `404`.

History filters use `period_end` inclusively. `limit` defaults to 20 and is
bounded to 1..100; `offset` defaults to 0.

## Deterministic policy

The report period is the Risk Evaluation date and the six preceding local
record dates. Daily Record values are averaged only across non-null values, and
each change records its own `sample_days`. Baseline values come from the exact
Baseline referenced by the Risk Evaluation.

Risk Engine `top_factor_codes` select up to three actions from the versioned
`recovery-catalog-v1` catalog. The LLM never selects an action, changes a
number, calculates risk, or produces the fixed disclaimer.

Raw journal text is not sent to report generation in this MVP.

## Transaction boundary

```text
authenticated source reads
-> immutable facts and provenance snapshot
-> read transaction rollback
-> one AI request or deterministic fallback
-> fresh write transaction
-> source rows lock and snapshot revalidation
-> append-only report insert
```

If source data changed during generation, POST returns `409` and stores no
report. Legacy Daily Records that cannot satisfy the shared contract return
`503`; missing values are never guessed.

## LLM failure and provenance

AI service timeout, connection failure, non-2xx response, malformed JSON,
schema mismatch, changed identifiers, or prohibited medical language all use
the deterministic template fallback. The API still returns `201`.

Stored provenance includes:

```text
risk_evaluation_id
period_start / period_end
facts snapshot
selected actions
catalog_version
prompt_version
generation_status
model_name
generated_at
```

`generation_status` is `llm_generated` or `template_fallback`. `model_name` is
null for fallback reports.

Migration `20260730_0007` creates the append-only report table. Downgrade is
blocked while generated report history exists.
