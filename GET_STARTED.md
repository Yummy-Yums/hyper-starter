# Getting Started

This walks through the full local flow:

**tenant -> first API key -> sandbox queued -> reconciler creates VM -> sandbox running -> exec/stop**

Run all commands from the repository root.

## 1. Create a virtual environment, install, configure, and start

### Create and activate the virtual environment

The project uses Python 3.11. Create the local `.venv` and activate it:

```bash
uv venv --python 3.11
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
uv venv --python 3.11
.venv\Scripts\Activate.ps1
```

If you are not using `uv`, create the environment with the standard library:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### Install dependencies

```bash
uv sync --all-extras
cp .env.example .env
```

`uv sync` will also create `.venv` automatically if it does not exist.

Edit `.env` and set an admin key:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./hyper.db
ADMIN_API_KEY=some-local-admin-secret
ENGINE_BACKEND=fake
```

Apply migrations and start the API:

```bash
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

`hyper.db` is the default SQLite database. Running `alembic upgrade head` is only necessary for a fresh database.

## 2. Create a tenant and first API key

There is no public endpoint for creating the very first API key, so bootstrap it with a script:

```bash
.venv/bin/python - <<'PY'
import asyncio

from app.api.schemas import ApiKeyCreate, TenantCreate
from app.db.session import SessionFactory
from app.services.api_keys import ApiKeyService
from app.services.tenants import TenantService


async def main() -> None:
    async with SessionFactory() as session:
        tenant = await TenantService(session).create(TenantCreate(name="acme"))
        key = await ApiKeyService(session).create(
            tenant.id, ApiKeyCreate(name="bootstrap")
        )
        print(f"TENANT_ID={tenant.id}")
        print(f"API_KEY={key.key}")


asyncio.run(main())
PY
```

Save the printed API key. The plaintext key is shown only at creation.

```bash
export API_KEY="<key-from-script>"
```

## 3. Create a sandbox

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sandboxes \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "image": "alpine",
    "vm_type": "micro",
    "expires_at": "2026-12-31T00:00:00Z"
  }'
```

The sandbox is created with `status="queued"`. The API does not start VMs directly.

## 4. Create the VM

Run the reconciler worker once:

```bash
.venv/bin/python - <<'PY'
import asyncio

from app.api.deps import get_engine
from app.db.session import SessionFactory
from app.workers.reconciler import reconcile_once


async def main() -> None:
    engine = get_engine()
    try:
        async with SessionFactory() as session:
            changed = await reconcile_once(session, engine)
            print(f"reconciled={changed}")
    finally:
        close = getattr(engine, "close", None)
        if close is not None:
            await close()


asyncio.run(main())
PY
```

`get_engine()` selects the backend from `.env`:

- `ENGINE_BACKEND=fake` (default) simulates the VM.
- `ENGINE_BACKEND=grpc` calls the real Hyper service at `GRPC_TARGET`.

For gRPC, the first run calls `LoadImage` for the sandbox image, which can take several minutes. Set `GRPC_TARGET`, `GRPC_ARCH`, and `GRPC_USE_TLS` as needed.

## 5. Use the sandbox

Set the sandbox id returned by the create request:

```bash
export SANDBOX_ID="<id-from-create-response>"
```

List and inspect sandboxes:

```bash
curl -H "Authorization: Bearer $API_KEY" \
  http://127.0.0.1:8000/api/v1/sandboxes

curl -H "Authorization: Bearer $API_KEY" \
  http://127.0.0.1:8000/api/v1/sandboxes/$SANDBOX_ID
```

Execute a command:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sandboxes/$SANDBOX_ID/exec \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"command":["echo","hello"]}'
```

Fork the sandbox:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sandboxes/$SANDBOX_ID/fork \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Stop the sandbox:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sandboxes/$SANDBOX_ID/stop \
  -H "Authorization: Bearer $API_KEY"
```

## 6. Manage API keys

Create an additional key:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/api-keys \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci"}'
```

List keys:

```bash
curl -H "Authorization: Bearer $API_KEY" \
  http://127.0.0.1:8000/api/v1/api-keys
```

Revoke a key:

```bash
curl -X DELETE \
  -H "Authorization: Bearer $API_KEY" \
  http://127.0.0.1:8000/api/v1/api-keys/<key-id>
```

Keys are tenant-scoped. The plaintext key is only returned by the create call.

## 7. Admin tenant routes

These require the `X-Admin-Key` value configured as `ADMIN_API_KEY` in `.env`.

```bash
export ADMIN_KEY="some-local-admin-secret"

# Create a tenant
curl -X POST http://127.0.0.1:8000/api/v1/admin/tenants \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"acme-2","max_running_sandboxes":5}'

# List tenants
curl -H "X-Admin-Key: $ADMIN_KEY" \
  http://127.0.0.1:8000/api/v1/admin/tenants
```

Admin routes can create tenants, but they do not create the tenant's first API key. Use the bootstrap script in step 2 for that.

## 8. Workers and expiry

Workers are plain async functions, not background services started by the API. Call them from cron, a job runner, or your own worker process.

- `reconcile_once(session, engine)` moves queued sandboxes to running.
- `run_reaper_once(session, engine)` stops expired or idle sandboxes.

The reaper uses `SANDBOX_IDLE_TIMEOUT_SECONDS` from `.env`, defaulting to `1800`.

## Notes

- Requests are rate limited per tenant by `RATE_LIMIT_PER_MINUTE`, default `60`.
- SQLite runs in WAL mode with foreign keys enabled and a 30-second busy timeout.
- Tests apply Alembic migrations to temporary SQLite databases; they do not use `create_all()`.
- For a real VM backend, set `ENGINE_BACKEND=grpc` and configure `GRPC_TARGET`. The first VM creation also loads the OCI image and can take several minutes.
