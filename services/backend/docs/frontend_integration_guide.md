# Frontend Integration Guide

This guide orients a frontend developer wiring a screen to the Re:Mind
backend. It answers "which call do I make, in what order, and what do I render
when a field is missing".

It is deliberately not a per-endpoint reference. The authoritative field-level
documents remain:

- [`behavioral_daily_record_api.md`](behavioral_daily_record_api.md)
- [`behavioral_baseline_api.md`](behavioral_baseline_api.md)
- [`emotion_analysis_orchestration.md`](emotion_analysis_orchestration.md)
- [`risk_evaluation_api.md`](risk_evaluation_api.md)
- [`recovery_report_api.md`](recovery_report_api.md)
- [`burnout_risk_engine_v1.md`](burnout_risk_engine_v1.md)

The whole sequence below is exercised end to end by
`tests/test_e2e_demo_flow.py`. That test is the executable version of this
document; if the two disagree, the test is correct.

## 1. Authentication

```text
POST /auth/signup   -> 201 { "id", "email", "name", "user_type" }
POST /auth/login    -> 200 { "access_token", "token_type": "bearer" }
```

Both take the same body:

```json
{
  "email": "demo@example.com",
  "password": "correct-horse-battery-staple1!"
}
```

Signup does not return a token. Call login afterwards and keep
`access_token`. Every endpoint in this guide except signup and login requires:

```text
Authorization: Bearer <access_token>
```

### Password strength

Signup (`UserCreate`) and password change (`PasswordUpdate` on
`PATCH /users/me/password`) both enforce the same four rules:

| Rule | Rule message |
| --- | --- |
| At least 8 characters | `비밀번호는 8자 이상이어야 합니다.` |
| At least one letter (`A-Za-z`) | `비밀번호에 영문자를 포함해야 합니다.` |
| At least one digit (`0-9`) | `비밀번호에 숫자를 포함해야 합니다.` |
| At least one special character | `비밀번호에 특수문자를 포함해야 합니다.` |

The accepted special characters are exactly:

```text
!@#$%^&*()_+-=[]{};':"\|,.<>/?
```

A violation is a `422` in the standard validation shape, with the rule message
carried in `msg` behind Pydantic's `Value error, ` prefix:

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["password"],
      "msg": "Value error, 비밀번호는 8자 이상이어야 합니다."
    }
  ]
}
```

Rules are checked in the order above and only the first failure is reported, so
a client-side validator should show all four requirements up front rather than
relaying one message at a time. The canonical definition lives in
`app/schemas/user.py` (`SPECIAL_CHARS`, `_check_password_strength`).

## 2. Consent gate

```text
POST   /api/v1/consents            -> 201
GET    /api/v1/consents            -> 200 (current status per consent type)
DELETE /api/v1/consents/{type}     -> 201 (withdrawal is a new history row)
```

```json
{
  "consent_type": "health_data",
  "source": "onboarding_screen"
}
```

Two consent types gate two different writes:

| Consent type | Required before |
| --- | --- |
| `health_data` | `POST` and `PUT /api/v1/behavioral-records` |
| `emotion_diary` | `POST /api/v1/emotion-analyses` |

Without the matching consent those writes return `403` with detail
`health_data 동의가 필요합니다` or `emotion_diary 동의가 필요합니다`. This is
the first thing a frontend hits: the pipeline cannot start at all until
`health_data` is granted, so grant both during onboarding rather than lazily on
first write.

Withdrawal is append-only. `DELETE` stores a withdrawal row rather than
deleting the grant, and the *latest* row decides the current state, so a
withdrawn user gets the same `403` as one who never consented. Re-granting is
another `POST`.

**GET and DELETE endpoints are never consent-gated.** Reads and deletes stay
open by design, so a user who has withdrawn consent can still see and erase
their own data. Only writes are blocked.

## 3. Recommended home-screen call sequence

Two calls, in parallel, are enough to paint the home screen:

```text
GET /api/v1/dashboard    -> the aggregated content to display
GET /api/v1/readiness    -> which screen or CTA to show
```

Neither recomputes anything. `dashboard` collects the latest stored artifacts;
`readiness` collapses the same snapshot into one funnel state. Both are
authenticated-user-scoped and return `401` only.

```json
{
  "record_status": { "today_recorded": true, "recorded_days": 8 },
  "baseline": {
    "status": "ready",
    "sample_days": 7,
    "window_end": "2026-08-04",
    "created_at": "2026-08-05T02:00:00Z"
  },
  "latest_risk": {
    "level": "moderate",
    "date": "2026-08-05",
    "top_factors": ["sleep_decrease", "rest_decrease", "workload_increase"]
  },
  "latest_report": {
    "id": "report-id",
    "headline": "수면 시간이 줄었어요 생활 리듬을 함께 살펴봤어요.",
    "generation_status": "llm_generated",
    "generated_at": "2026-08-05T02:05:00Z"
  }
}
```

`readiness` returns `{ "state": "..." }` with one of five values. The state
means "the furthest artifact that currently exists for this user", not "what
the user is allowed to request next". It is monotonic: it only moves forward.

| `state` | What exists | Suggested screen / CTA |
| --- | --- | --- |
| `insufficient_records` | fewer than 7 daily records | Onboarding-style record screen. Show progress toward 7 days using `recorded_days`, e.g. `n일 더 기록하면 분석을 시작할 수 있어요`, with a progress indicator. Primary CTA: record today. |
| `baseline_pending` | 7+ records, no ready baseline | Records are sufficient but nothing is computed yet. Primary CTA `평소 기준 계산하기` calling `POST /api/v1/baselines` with `as_of_date` = yesterday. |
| `baseline_ready` | a ready baseline, no evaluation | Show the baseline summary. Primary CTA `오늘 상태 확인하기` calling `POST /api/v1/risk-evaluations` for today, after the day's record exists. Optionally post `POST /api/v1/emotion-analyses` first so the evaluation carries an emotion signal. |
| `risk_evaluation_ready` | at least one risk evaluation | Show `latest_risk.level` and `top_factors` as the main card. Primary CTA `회복 리포트 받기` calling `POST /api/v1/recovery-reports` with `latest_risk`'s evaluation id (fetch it from `GET /api/v1/risk-evaluations/latest`; the dashboard summary does not carry the id). |
| `recovery_report_ready` | at least one recovery report | Steady state. Show `latest_report.headline` linking to the full report, plus today's record CTA if `today_recorded` is false. |

Ordering constraints worth knowing before you build the CTAs:

- A baseline needs at least 7 distinct dates with data inside its window.
- A risk evaluation needs a daily record for the requested date **and** a ready
  baseline whose `window_end` is strictly before that date. Computing a
  baseline `as_of` today and then evaluating today returns `409`.
- An emotion analysis needs a daily record for the same date first (`404`
  otherwise), so record before journaling.
- A recovery report needs a stored risk evaluation id.

## 4. Error codes

Statuses a frontend will actually hit. Details are the literal strings the
route handlers return.

| Status | Endpoint | `detail` | Frontend action |
| --- | --- | --- | --- |
| `401` | any authenticated endpoint | `Could not validate credentials` | Missing, malformed, or expired token. Response carries `WWW-Authenticate: Bearer`. Send back to login. |
| `401` | `POST /auth/login` | `이메일 또는 비밀번호가 올바르지 않습니다.` | Inline form error. Do not distinguish unknown email from wrong password. |
| `401` | `PATCH /users/me/password` | `현재 비밀번호가 일치하지 않습니다` | Inline error on the current-password field only. |
| `403` | `POST`/`PUT /api/v1/behavioral-records` | `health_data 동의가 필요합니다` | Route to the consent screen, then retry. |
| `403` | `POST /api/v1/emotion-analyses` | `emotion_diary 동의가 필요합니다` | Same, for the diary consent. |
| `404` | `POST /api/v1/emotion-analyses`, `POST /api/v1/risk-evaluations`, `GET`/`PUT`/`DELETE /api/v1/behavioral-records/{date}` | `Behavioral record not found.` | No record for that date. Prompt to record that day first. Another user's data returns the same `404`. |
| `404` | `POST /api/v1/recovery-reports` | `Risk evaluation not found.` | Stale or foreign evaluation id. Re-fetch `GET /api/v1/risk-evaluations/latest`. |
| `404` | `GET /api/v1/risk-evaluations/latest` | `Risk evaluation not found.` | Empty state, not an error. |
| `404` | `GET /api/v1/recovery-reports/latest` | `Recovery report not found.` | Empty state. |
| `404` | `GET /api/v1/baselines/latest-ready` | `Ready baseline not found.` | Empty state; offer the baseline CTA. |
| `404` | `GET /api/v1/emotion-analyses/latest` | `No emotion analysis results found.` | Empty state. |
| `404` | `GET /api/v1/emotion-analyses/{id}` | `Emotion analysis result not found.` | Empty state. |
| `404` | `DELETE /api/v1/consents/{type}` | `해당 동의 항목에 대한 활성 동의가 없습니다` | Already withdrawn. Refresh `GET /api/v1/consents`. |
| `409` | `POST /auth/signup` | `이미 가입된 이메일입니다.` | Offer login instead. |
| `409` | `POST /api/v1/behavioral-records` | `A behavioral record already exists for this date.` | Switch to `PUT /api/v1/behavioral-records/{date}`. |
| `409` | `POST /api/v1/risk-evaluations` | `A ready baseline before the evaluation date is required.` | Baseline missing or its `window_end` is not before the date. Run the baseline CTA with an earlier `as_of_date`. |
| `409` | `POST /api/v1/risk-evaluations` | `Risk evaluation inputs changed; retry the evaluation.` | Source rows changed mid-request. Retry once automatically. |
| `409` | `POST /api/v1/recovery-reports` | `Recovery report inputs changed; retry generation.` | Same, retry once. |
| `422` | `POST /auth/signup`, `PATCH /users/me/password` | password-strength message (section 1) | Inline field error. |
| `422` | `POST`/`PUT /api/v1/behavioral-records` | `date cannot be in the future for the submitted time_zone.` | Clamp the date picker to the device's local today. |
| `422` | `PUT /api/v1/behavioral-records/{date}` | `date in the request body must match the URL date.` | Client bug. |
| `422` | `GET /api/v1/behavioral-records` | `date_from and date_to must be provided together.` / `date_from must be on or before date_to.` / `Date range cannot exceed 28 inclusive days.` | Fix the range before sending; omit both for the default latest 14 UTC days. |
| `422` | `POST /api/v1/emotion-analyses` | `record_date cannot be in the future.` | Compared against UTC today, not device local time. |
| `422` | `POST /api/v1/baselines` | `as_of_date cannot be in the future.` | Use yesterday or earlier. |
| `422` | `POST /api/v1/risk-evaluations` | `date cannot be in the future for the record timezone.` | The record's own IANA timezone decides, not the device's. |
| `422` | any | list of `{ "type", "loc", "msg" }` | Framework validation. Only these three keys are exposed; submitted values are never echoed back. Map `loc` to the field. |
| `503` | behavioral-record reads, `POST /api/v1/risk-evaluations`, `POST /api/v1/recovery-reports` | `Behavioral record field metadata is unavailable.` / `Risk evaluation input metadata is unavailable.` / `Recovery report inputs are unavailable.` | Legacy rows missing field metadata. Not retryable by the user; show a neutral "이 기간의 기록을 불러올 수 없어요" state and report it. |
| `503` | `POST /api/v1/emotion-analyses` | `Emotion analysis service is unavailable.` | Downstream AI service down or unconfigured. Retryable later; the request stored nothing. |
| `504` | `POST /api/v1/emotion-analyses` | `Emotion analysis service timed out.` | Retryable. Nothing was stored. |
| `502` | `POST /api/v1/emotion-analyses` | `Emotion analysis service rejected the request.` / `Emotion analysis service returned an invalid response.` | Not user-fixable. Nothing was stored. |
| `500` | any | operation-specific message, e.g. `Risk evaluation could not be calculated.` | Generic failure banner. Internal details are never returned. |

Note the asymmetry: emotion analysis surfaces downstream AI failures as
`502`/`503`/`504`, whereas recovery-report generation never does — a failed
Gemini call still returns `201` with a template fallback. See section 6.

## 5. Handling missing data

Every content field on `GET /api/v1/dashboard` can legitimately be absent. A
fresh account returns:

```json
{
  "record_status": { "today_recorded": false, "recorded_days": 0 },
  "baseline": null,
  "latest_risk": null,
  "latest_report": null
}
```

`record_status` is the only block that is always present.

| Field | Absent means | Render |
| --- | --- | --- |
| `record_status.today_recorded` | `false` — no record for today in **UTC** | Show the record CTA. Because the flag is UTC-based while record dates are submitted in the user's IANA `time_zone`, it can disagree with the device's calendar near midnight. Treat it as a nudge, not a hard truth; do not block a submission because of it. |
| `record_status.recorded_days` | count of all stored records, never null | Progress toward the 7-day minimum. It is a UI hint only: it counts every record ever stored, not the rolling window the baseline service actually uses. Do not use it to predict whether `POST /api/v1/baselines` will return `ready`; the response's own `status` field is the answer. |
| `baseline` | `null` — no *ready* baseline exists | Hide baseline comparisons entirely. When present it is always `status: "ready"`; the dashboard never surfaces an `insufficient` snapshot, so do not build UI branches for other statuses here. `POST /api/v1/baselines` can still return `insufficient` and that is a `201`, not an error. |
| `latest_risk` | `null` — no evaluation yet | Hide the risk card. Never substitute a default level; "no data" and "low risk" must not look alike. |
| `latest_risk.top_factors` | may be `[]` even when `latest_risk` exists | An evaluation with no contributing factors. Render the level without a factor list rather than an empty list widget. At most three codes are returned. |
| `latest_report` | `null` — no report yet | Hide the report entry point. |

Two ids are intentionally *not* in the dashboard payload: the risk evaluation
id and the baseline id. A screen that needs them calls
`GET /api/v1/risk-evaluations/latest` or `GET /api/v1/baselines/latest-ready`.

Because the funnel is monotonic, a populated `latest_risk` with a `null`
`baseline` is not a valid combination to design for, but a populated
`latest_report` alongside a `today_recorded: false` is common — yesterday's
report with today's record still missing.

## 6. Recovery report `generation_status`

`generation_status` on a recovery report is one of two values from
`app.domain.recovery.models.ReportGenerationStatus`:

| Value | Meaning | `model_name` |
| --- | --- | --- |
| `llm_generated` | Gemini produced the prose | model id string |
| `template_fallback` | deterministic template produced the prose | `null` |

**Both are equally valid content and both arrive as `201`.** The fallback is
not an error state and not degraded data: every number, factor, period, and
recommended action in the report is computed deterministically by the backend
in both cases. The LLM only writes the surrounding sentences, and it is never
allowed to select an action, change a value, or produce the disclaimer. A
fallback report is triggered by a timeout, a connection failure, a malformed
response, or generated text that failed validation — all of which the backend
has already absorbed by the time the frontend sees the response.

Recommendation: **render both identically**. Do not show a warning, an error
color, a retry button, or "AI unavailable" copy for `template_fallback` — that
would tell the user their report is worse when it is not. If the product wants
transparency, the most that is justified is a small neutral provenance line in
a details/metadata section (e.g. `AI 생성` vs `기본 문안`), the same weight as
a timestamp. Keep it out of the primary card.

Do use the field for telemetry: a rising `template_fallback` rate is a real
signal about the AI service, and the frontend is the cheapest place to observe
it.

## 7. Emotion analysis `provisional`

`POST /api/v1/emotion-analyses` returns `201` with a `provisional` boolean and
a nullable `emotion`. `provisional: true` means **the model declined to commit
to a label**, not that the call failed. It happens two ways:

- the six-class model's confidence or margin did not clear the versioned
  abstention threshold; or
- the neutral gate classified the entry as neutral and the six-class model was
  never invoked (`neutral_gate_decision: "neutral"`).

In both cases `emotion` is `null`. In the neutral-gate case `predicted_emotion`
and `probabilities` are null as well; in the low-confidence case
`predicted_emotion` keeps the raw argmax for provenance.

```json
{
  "record_date": "2026-08-05",
  "predicted_emotion": null,
  "emotion": null,
  "confidence": null,
  "provisional": true,
  "is_uncertain": true,
  "neutral_gate_decision": "neutral"
}
```

What to render:

- **Never show a specific emotion label when `provisional` is true.** In
  particular, do not fall back to `predicted_emotion` for display. That value
  exists as provenance precisely because the system decided it was not
  trustworthy enough to state.
- Show a neutral acknowledgement instead, e.g. `오늘은 특정 감정으로 보기
  어려웠어요` or `평온한 쪽에 가까웠어요`, and keep the entry in the diary
  history.
- Do not treat it as an error, do not offer a retry, and do not prompt the user
  to rewrite the entry. The result is stored and final.
- Suppress emotion-dependent visuals (color coding, emoji, mood charts) for
  that date rather than defaulting them to neutral, so the chart does not imply
  a measurement that was never made.

The downstream effect is consistent with this: the risk engine keeps the
analysis id as provenance (`emotion_analysis_id` is non-null on the evaluation)
but passes no emotion signal, so the evaluation is behavioral-only. A
provisional entry therefore never moves the risk level, and a frontend should
not imply that it did.
