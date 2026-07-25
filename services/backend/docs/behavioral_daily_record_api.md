# Behavioral Daily Record API

Authenticated users can create and read only their own daily behavioral
records. The API reuses the persistence `DailyRecordCreate` and
`DailyRecordRead` schemas and never accepts a client-provided `user_id`.

## Endpoints

- `POST /api/v1/behavioral-records`
- `GET /api/v1/behavioral-records/{record_date}`
- `GET /api/v1/behavioral-records?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

Creation returns `201`. A duplicate user/date returns `409`, and a missing
record returns `404`. The route owns commit and rollback; the repository only
flushes.

`record_date` cannot be later than the current date in the submitted IANA
`timezone`. This preserves the producer's local date boundary without trusting
the server's local timezone.

Range queries are inclusive and return the persistence repository's existing
newest-date-first order. With no range, the API returns the latest 14 UTC
calendar days. A range may contain at most 28 inclusive days, and `date_from`
and `date_to` must be provided together.

This API does not invoke emotion analysis, calculate a baseline, execute the
risk engine, or persist a risk evaluation.
