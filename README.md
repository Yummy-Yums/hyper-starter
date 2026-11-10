# Hyper Starter

A runnable FastAPI starter based on the package list and project layout in your screenshots. It uses **uv** for dependency management.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- SQLite is the default database. PostgreSQL is optional; set `DATABASE_URL` to a PostgreSQL async URL to switch.

## Quick start

```bash
uv sync --all-extras
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open:
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

`uv sync --all-extras` installs core dependencies plus the optional `observability` and `dev` groups. If you only want the runtime packages, use `uv sync`.

## Useful commands

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy app
uv lock
```

## Layout

```text
app/
  main.py                 # FastAPI app factory and lifespan
  config.py               # pydantic-settings
  errors.py               # domain error types and HTTP envelope
  api/
    admin.py              # X-Admin-Key dependency
    auth.py               # bearer API-key authentication
    rate_limit.py         # per-tenant slowapi limiter
    deps.py               # shared dependencies
    routes/
      api_keys.py
      health.py
      sandboxes.py
      tenants.py
    schemas.py             # request/response models
  db/
    base.py
    models.py
    session.py
    migrations/            # Alembic migration environment
  services/
    api_keys.py            # key generation, hashing, auth, revocation
    sandboxes.py           # sandbox domain service
    tenants.py             # tenant admin service
    quota.py
    catalog.py
    exec_runner.py
  engine/
    base.py                # engine protocol/result/errors
    fake.py                # in-memory test double
    grpc_engine.py         # production adapter placeholder
  workers/
    reaper.py
    reconciler.py
proto/
  hyper/grpc/v0/hyper.proto
tests/
```

## Database

The async SQLAlchemy session factory is configured from `DATABASE_URL`, and the initial schema is in `app/db/migrations/versions/0001_initial.py`. The default production database is `sqlite+aiosqlite:///./hyper.db`. Apply migrations with `uv run alembic upgrade head`.

SQLite connections enable WAL mode, foreign keys, a 30-second busy timeout, and `synchronous=NORMAL`. The test suite applies the same Alembic migrations to temporary SQLite databases; `create_all()` is intentionally not used.

To create a migration after changing models:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

## Authentication and tenancy

Tenant-owned `/api/v1` routes require an API key:

```bash
curl -H "Authorization: Bearer <api-key>" http://127.0.0.1:8000/api/v1/sandboxes/<id>
```

Keys are looked up by their 8-character prefix, verified with SHA-256, and rejected when revoked. `last_used_at` is updated at most once per minute. The tenant id comes from the key, never from the request, and all tenant-owned repository queries are scoped by it. Requests are rate limited per tenant by `RATE_LIMIT_PER_MINUTE` (default `60`).

Admin tenant routes use a separate `X-Admin-Key` header checked against `ADMIN_API_KEY`:

```text
POST   /api/v1/admin/tenants
GET    /api/v1/admin/tenants
GET    /api/v1/admin/tenants/{id}
PATCH  /api/v1/admin/tenants/{id}
DELETE /api/v1/admin/tenants/{id}
```

Tenant API keys are managed at `POST/GET /api/v1/api-keys` and `DELETE /api/v1/api-keys/{id}`. The plaintext key is returned only by the create endpoint.

Tenant-owned sandbox routes are `POST/GET /api/v1/sandboxes`, `GET /api/v1/sandboxes/{id}`, and `POST /api/v1/sandboxes/{id}/fork|exec|stop`. Execution uses `ENGINE_BACKEND` (`fake` by default, or `grpc`).

## Workers

Workers are plain async functions that take a session and an `Engine`:

- `reconcile_once()` moves `queued` sandboxes to `running` by creating a VM and setting `vm_id`. Engine failures mark the sandbox `failed` with an internal `failure_reason`.
- `run_reaper_once()` stops sandboxes past `expires_at` or idle for longer than `SANDBOX_IDLE_TIMEOUT_SECONDS` (default `1800`), setting `status="stopped"` and `stopped_at`.

Both claim rows with `FOR UPDATE SKIP LOCKED` on PostgreSQL and re-check the row status after locking. Engine calls use the sandbox id as an idempotency key, so a retry after a crash does not create a second VM or double-stop an existing one. No scheduler is included; call them from your job runner.

## gRPC stubs

The example `.proto` is intentionally small. Generate Python stubs with:

```bash
uv run python -m grpc_tools.protoc \
  -I proto \
  --python_out=app/engine/gen \
  --grpc_python_out=app/engine/gen \
  proto/hyper/grpc/v0/hyper.proto
```

The generated directory is ignored by Git by default only if you add it to `.gitignore`; commit generated stubs if you want reproducible builds, and record the `.proto` source revision/hash for vendored schemas.

## Notes

- Dependency versions are deliberately not hard-coded. Resolve and commit `uv.lock` in your environment using `uv lock`.
- `FOR UPDATE SKIP LOCKED` is a PostgreSQL-specific pattern; use it for worker claim queries only when running PostgreSQL.
- `slowapi` is included as a rate-limiting option; the starter does not apply a global rate limit by default.
- OpenTelemetry dependencies are optional. Instrumentation setup is left as an explicit next step rather than silently enabling exporters.
