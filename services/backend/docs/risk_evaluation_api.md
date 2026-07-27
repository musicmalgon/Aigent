# Risk Evaluation API

The risk-evaluation endpoints connect a user's daily behavioral record,
optional emotion analysis, historical ready baseline, rules engine, and
append-only evaluation history.

## Endpoints

All endpoints require bearer authentication. The authenticated user is the
only user scope accepted by the API; clients cannot submit a `user_id`.

### `POST /api/v1/risk-evaluations`

Request:

```json
{
  "date": "2026-07-27"
}
```

The request body is strict. Unknown fields are rejected. The endpoint selects:

- the authenticated user's Daily Record for `date`;
- the latest Emotion Analysis for the same user and date, when one exists;
- the latest ready Baseline with at least seven sample days and
  `window_end < date`.

The record's IANA `time_zone` defines whether `date` is in the future. Emotion
Analysis is optional and its provenance is returned as `null` when absent.
Every successful request appends a new evaluation; repeated evaluation of the
same date never overwrites prior results.

The complete shared Daily Record contract is validated before its timezone is
trusted. Therefore missing or invalid legacy field metadata returns `503` even
when the requested date would otherwise be in the future; the API does not use
an untrusted legacy timezone merely to return `422`.

The endpoint completes input reads and rolls back their read transaction before
running the rules engine. It then re-verifies the selected provenance and
stores the result in a separate write transaction.

### `GET /api/v1/risk-evaluations/latest`

Returns the authenticated user's latest dated evaluation, ordered by
`evaluated_at`, `created_at`, then the stable evaluation ID. Undated legacy
evaluations are not part of this public API. An evaluation is also omitted when
deletion of its backing Daily Record has set `daily_record_id` to `null`,
because public evaluation provenance requires a Daily Record ID. If no
eligible evaluation remains, this endpoint returns `404`.

### `GET /api/v1/risk-evaluations`

Returns append-only dated history in the same descending order. `date_from`
and `date_to` independently apply inclusive Daily Record date filters.
Pagination uses `limit` (default 20, range 1 through 100) and `offset`
(default 0). Rows whose backing Daily Record was deleted and whose
`daily_record_id` is consequently `null` are omitted rather than serialized
with incomplete public provenance.

## Response

Persistence and provenance metadata are kept outside the engine result:

```json
{
  "id": "evaluation-id",
  "user_id": "authenticated-user-id",
  "date": "2026-07-27",
  "evaluated_at": "2026-07-27T03:00:00Z",
  "daily_record_id": "daily-record-id",
  "emotion_analysis_id": null,
  "baseline_id": "baseline-id",
  "created_at": "2026-07-27T03:00:00Z",
  "result": {
    "score": 12.5,
    "level": "low",
    "is_provisional": false,
    "baseline_status": "ready",
    "data_quality": "sufficient",
    "category_scores": {},
    "factors": [],
    "summary": {
      "top_factor_codes": [],
      "available_signal_count": 7,
      "missing_signal_count": 0,
      "available_category_count": 5,
      "missing_category_count": 0
    },
    "engine_version": "burnout-risk-rules-v1"
  }
}
```

`result` is validated against the shared Burnout Risk Engine response contract.
The public `date` maps to persistence `record_date`, and
`emotion_analysis_id` maps to `emotion_analysis_result_id`.

## Error policy

- `404`: the user's Daily Record or latest evaluation does not exist. This
  response does not disclose whether another user owns data for the date.
- `409`: no eligible ready Baseline exists, or selected inputs changed between
  reading and storing.
- `422`: request validation failed, the date is in the future in the record's
  IANA timezone, or the history range is reversed.
- `503`: legacy Daily Record metadata is absent or cannot be interpreted
  against the shared contract. No value is inferred or repaired at runtime.
- `500`: loading, calculating, or storing failed. Database and internal error
  details are not returned.

Legacy rows without `source_by_field` and `coverage_by_field` require an
explicit audited backfill before they can be evaluated. The API deliberately
does not invent metadata.
