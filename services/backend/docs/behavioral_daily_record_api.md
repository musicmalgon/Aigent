# Behavioral Daily Record API

Authenticated users can create and read only their own daily behavioral
records. The public request and response models mirror
`packages/contracts/schemas/behavioral_daily_record.schema.json`; persistence
models and ORM rows are not wire contracts.

The create body contains every shared field except `user_id`, which is derived
from the authenticated user. All nullable metric keys remain required and use
JSON `null` for unavailable values. Responses contain the complete shared
record, including the server-derived `user_id`, and do not expose persistence
metadata such as `id`, timestamps, legacy `source`, `data_completeness`, or
`subjective_stress`.

The API maps shared names to existing physical names explicitly:

- `date` to `record_date`;
- `time_zone` to `timezone`;
- `work_or_study_minutes` to `study_work_minutes`.

`source_by_field` and `coverage_by_field` must each contain exactly the ten
nullable behavioral metric keys from the shared contract. Null values require
`unavailable` coverage; observed values require `complete` or `partial`
coverage and cannot use `not_provided` as their source.

## Endpoints

- `POST /api/v1/behavioral-records`
- `GET /api/v1/behavioral-records/{record_date}`
- `GET /api/v1/behavioral-records?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

Creation returns `201`. A duplicate user/date returns `409`, and a missing
record returns `404`. The route owns commit and rollback; the repository only
flushes.

Rows created before field-level metadata was introduced cannot satisfy the
shared response contract until an approved backfill supplies both metadata
objects. Reads that encounter such a row return `503`; the API does not infer
or fabricate provenance.

`date` cannot be later than the current date in the submitted IANA
`time_zone`. This preserves the producer's local date boundary without trusting
the server's local timezone.

Range queries are inclusive and return the persistence repository's existing
newest-date-first order. With no range, the API returns the latest 14 UTC
calendar days. A range may contain at most 28 inclusive days, and `date_from`
and `date_to` must be provided together.

This API does not invoke emotion analysis, calculate a baseline, execute the
risk engine, or persist a risk evaluation.
