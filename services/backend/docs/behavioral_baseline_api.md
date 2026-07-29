# Behavioral Baseline API

The Baseline API creates and reads append-only personal baseline snapshots for
the authenticated user. It does not run the burnout risk engine or create a
risk evaluation.

## Endpoints

```text
POST /api/v1/baselines
GET  /api/v1/baselines/latest-ready
GET  /api/v1/baselines
```

Create a baseline with an explicit UTC date:

```json
{
  "as_of_date": "2026-07-27",
  "window_days": 14
}
```

`as_of_date` is required and cannot be in the future. `window_days` defaults
to 14 and accepts inclusive values from 14 through 28. The aggregation period
is also inclusive:

```text
window_start = as_of_date - (window_days - 1)
window_end   = as_of_date
```

For example, a 14-day baseline ending on `2026-07-27` covers
`2026-07-14` through `2026-07-27`.

## Aggregation policy

The API calls the existing `behavioral-baseline-mean-v1` service. It:

- scopes Daily Records and Emotion Analysis results to the authenticated user;
- excludes rows outside the requested period;
- counts distinct dates with at least one behavioral metric or valid emotion
  result;
- selects the latest Emotion Analysis result for each date;
- excludes null values separately from each metric denominator;
- treats zero as a measured value;
- rounds persisted means to four decimal places;
- creates `ready` at seven or more sample days and `insufficient` otherwise.

An `insufficient` result is a successful append-only snapshot and returns
`201 Created`.

## Append-only history

Every create request stores a new `BehavioralBaseline` row, including repeated
requests for the same period and algorithm version. Existing rows are never
updated, replaced, or deduplicated. Both `ready` and `insufficient` snapshots
remain in history.

`GET /api/v1/baselines/latest-ready` returns the latest ready row according to
creation time and a stable ID tie-breaker. It can therefore return an earlier
ready snapshot when the most recently created baseline is insufficient. It
returns `404` when the user has no ready baseline.

`GET /api/v1/baselines` returns creation history newest first. It supports:

- `status=ready|insufficient`;
- inclusive `date_from` and `date_to` filters over `window_end`;
- `limit` from 1 through 100, default 20;
- non-negative `offset`, default 0.

`date_from` and `date_to` are independent optional bounds. Supplying both
requires `date_from <= date_to`.

The API never accepts a client-supplied `user_id`, status, sample count,
algorithm version, or aggregate value. The Risk Evaluation API uses an
eligible stored baseline ID as provenance, but baseline creation does not
automatically execute the risk engine.

The response is the stored persistence snapshot represented by
`BaselineRead`. It is intentionally separate from the shared
`packages/contracts` behavioral-baseline wire schema, which describes a
different cross-service payload. This API does not claim conformance to that
shared schema and does not modify it.
