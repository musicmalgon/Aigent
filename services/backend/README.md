# Aigent Backend

The backend is a FastAPI service with SQLAlchemy models and Alembic-managed
schema migrations. Python 3.12 is the supported development version.

The internal behavioral and risk-result persistence layer is documented in
[`docs/behavioral_persistence.md`](docs/behavioral_persistence.md). The
orchestrated Risk Evaluation API and its transaction, error, and legacy-data
policies are documented in
[`docs/risk_evaluation_api.md`](docs/risk_evaluation_api.md).

## Dependency layout

- `requirements.txt`: production runtime dependencies
- `requirements-dev.txt`: runtime dependencies plus tests and static analysis

The backend environment is intentionally separate from `services/ai`.

## Local setup

### Windows PowerShell

```powershell
cd services\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `JWT_SECRET_KEY` in the untracked `.env` file.

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

### Bash

```bash
cd services/backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

The default development database is `sqlite:///./remind.db`. Test runs use a
separate temporary SQLite file and never use the configured development or
production database.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development`, `test`, or `production` |
| `DATABASE_URL` | SQLAlchemy database URL |
| `JWT_SECRET_KEY` | Secret used to sign access tokens; minimum 32 characters |
| `JWT_ALGORITHM` | `HS256`, `HS384`, or `HS512` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Positive lifetime, at most 7 days |
| `SQLADMIN_ENABLED` | Registers SQLAdmin only when explicitly enabled |
| `SQLADMIN_PATH` | Non-root path for the development admin UI |
| `AI_SERVICE_BASE_URL` | Internal Emotion and Recovery Report AI service URL |
| `STAGE2_BURNOUT_SIGNALS_ENABLED` | Opt-in capture/use of validated Stage 2 signals for recovery ranking |

When the AI service has the Stage 2 artifact configured, each emotion-diary
analysis also captures its informational burnout-signal payload. The recovery
report planner uses only labels marked both `active` and `validated` to rank
low-intensity actions; the payload never changes the Risk Engine score. Apply
the `20260820_0009` migration before enabling this path in a deployed backend.

Production startup fails when `JWT_SECRET_KEY` is missing or resembles a public
placeholder. Keep production secrets in the deployment secret manager. Do not
put them in source control, command output, logs, or `.env.example`.

Recovery Report behavior, deterministic recommendation policy, transaction
boundaries, and fallback semantics are documented in
`docs/recovery_report_api.md`.

SQLAdmin has no authentication in the current backend. It defaults to disabled
and can only be enabled when `APP_ENV=development`. Keep it bound to a trusted
local environment:

```dotenv
APP_ENV=development
SQLADMIN_ENABLED=true
SQLADMIN_PATH=/internal-admin
```

`APP_ENV=test` and `APP_ENV=production` reject enabled SQLAdmin.

## Demo seed data

`app/scripts/seed_demo_data.py` populates the configured database with three
demo accounts for the academic-festival presentation. It runs directly against
`DATABASE_URL` — no HTTP server needs to be running — but every derived artifact
(baseline, risk evaluation, recovery report) is produced by the same service
functions the API handlers call. Nothing is precomputed and inserted.

Apply migrations first, then run from `services/backend`:

```powershell
python -m alembic upgrade head
python -m app.scripts.seed_demo_data
```

The three accounts all use the password `Demo1234!` and are created with
`health_data` consent already granted, so they are not blocked by the
consent-gated write endpoints:

| Email | Demonstrates | Seeded artifacts |
| --- | --- | --- |
| `demo-insufficient@remind.example` | `insufficient_records` readiness | 4 daily records only (below `MINIMUM_SAMPLE_DAYS`), no baseline |
| `demo-normal@remind.example` | `baseline_ready` readiness | 21 stable daily records and a READY baseline, no risk evaluation |
| `demo-high-risk@remind.example` | Elevated risk from sleep and rest decline | 21 daily records (last 7 degraded), READY baseline, `high` risk evaluation, recovery report |

The high-risk account also has `emotion_diary` consent.

The AI service is optional. With it running and `GEMINI_API_KEY` configured, the
recovery report is stored as `llm_generated`; otherwise the generator degrades to
`template_fallback`, which is an equally valid demo state. Emotion analysis is
attempted only when the AI service answers its readiness probe, because emotion
results must always come from the live model — the script never fabricates one
and skips the step with a printed message instead.

The script is safe to re-run: it skips any scenario whose demo account already
exists rather than failing on a duplicate email.

## Schema migrations

Alembic is the schema source of truth. Importing the application does not call
`Base.metadata.create_all()` and does not create or modify tables.

Apply reviewed migrations:

```powershell
python -m alembic upgrade head
```

Create a candidate migration after changing SQLAlchemy models:

```powershell
python -m alembic revision --autogenerate -m "describe schema change"
```

Every generated migration must be reviewed for column nullability, defaults,
indexes, enum representation, upgrade safety, and downgrade behavior. Never
autogenerate against or apply an unreviewed migration to a shared database.

The initial revision creates an empty `users` table. SQLAlchemy's Python enum
mapping stores member names such as `JOB_SEEKER`, while API values remain
lowercase strings such as `job_seeker`.

### Existing databases

An existing database may already have a `users` table created by the former
startup `create_all()` behavior. Do not run the initial migration against that
database until its schema and data have been inspected and backed up.

If the existing schema is proven equivalent, an operator may establish the
baseline with:

```powershell
python -m alembic stamp 20260725_0001
```

`stamp` records migration state without changing the schema, so using it on a
non-equivalent database is unsafe. Existing enum data may include the historical
`EARLY_CAREER` member while the current model uses `JOB_SEEKER` and
`EARLY_CAREER_WORKER`. Any conversion requires a separately reviewed data
migration; this foundation does not transform existing values.

SQLite is used for local tests. PostgreSQL uses a native `usertype` enum and
has different enum-alteration, concurrency, and timezone behavior. Validate
future migrations on a disposable PostgreSQL environment before production.

## Verification

From `services/backend`:

```powershell
python -m pytest -q -p no:cacheprovider
python -m ruff check .
python -m mypy app tests alembic
python -m compileall app alembic
```

Migration round-trip tests use a temporary database and perform:

```text
upgrade head -> downgrade base -> upgrade head -> upgrade head
```

From the repository root, run the whole suite with both service roots available:

```powershell
$env:PYTHONPATH="services;services/backend"
python -m pytest -q -p no:cacheprovider
python -m ruff check .
python -m mypy services/backend
python -m compileall services/backend
```

Equivalent Bash setup:

```bash
PYTHONPATH="services:services/backend" python -m pytest -q -p no:cacheprovider
python -m ruff check .
python -m mypy services/backend
python -m compileall services/backend
```
