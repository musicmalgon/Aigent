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

Production startup fails when `JWT_SECRET_KEY` is missing or resembles a public
placeholder. Keep production secrets in the deployment secret manager. Do not
put them in source control, command output, logs, or `.env.example`.

SQLAdmin has no authentication in the current backend. It defaults to disabled
and can only be enabled when `APP_ENV=development`. Keep it bound to a trusted
local environment:

```dotenv
APP_ENV=development
SQLADMIN_ENABLED=true
SQLADMIN_PATH=/internal-admin
```

`APP_ENV=test` and `APP_ENV=production` reject enabled SQLAdmin.

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
