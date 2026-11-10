from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_engine
from app.api.rate_limit import limiter
from app.api.schemas import ApiKeyCreate, TenantCreate
from app.config import Settings
from app.db.session import get_session
from app.engine.fake import FakeEngine
from app.main import app
from app.repositories.sandboxes import SandboxRepository
from app.services.api_keys import ApiKeyService
from app.services.tenants import TenantService


@dataclass(frozen=True)
class Seeded:
    tenant_id: UUID
    key: str


@dataclass(frozen=True)
class ApiContext:
    client: httpx.AsyncClient
    seeded: Seeded
    engine: FakeEngine
    factory: async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture
async def api(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> AsyncIterator[ApiContext]:
    factory = session_factory
    async with factory() as session:
        tenant = await TenantService(session).create(
            TenantCreate(name="acme", max_running_sandboxes=5)
        )
        key = await ApiKeyService(session).create(
            tenant.id, ApiKeyCreate(name="test")
        )
        seeded = Seeded(tenant_id=tenant.id, key=key.key)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    fake_engine = FakeEngine()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_engine] = lambda: fake_engine
    monkeypatch.setattr(
        "app.api.admin.get_settings",
        lambda: Settings(admin_api_key="admin-secret"),
    )
    limiter.reset()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield ApiContext(
            client=client,
            seeded=seeded,
            engine=fake_engine,
            factory=factory,
        )

    app.dependency_overrides.clear()
    limiter.reset()


def auth_header(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def admin_header() -> dict[str, str]:
    return {"X-Admin-Key": "admin-secret"}


async def test_tenant_admin_routes(api: ApiContext) -> None:
    client = api.client

    missing = await client.post("/api/v1/admin/tenants", json={"name": "nope"})
    assert missing.status_code == 401
    wrong = await client.post(
        "/api/v1/admin/tenants",
        json={"name": "nope"},
        headers={"X-Admin-Key": "wrong"},
    )
    assert wrong.status_code == 401

    created = await client.post(
        "/api/v1/admin/tenants",
        headers=admin_header(),
        json={"name": "new-tenant", "max_running_sandboxes": 2},
    )
    assert created.status_code == 201
    tenant_id = created.json()["id"]

    listed = await client.get("/api/v1/admin/tenants", headers=admin_header())
    assert listed.status_code == 200
    assert tenant_id in [item["id"] for item in listed.json()]

    fetched = await client.get(
        f"/api/v1/admin/tenants/{tenant_id}", headers=admin_header()
    )
    assert fetched.status_code == 200

    updated = await client.patch(
        f"/api/v1/admin/tenants/{tenant_id}",
        headers=admin_header(),
        json={"name": "renamed", "max_exec_timeout_ms": 1000},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "renamed"
    assert updated.json()["max_exec_timeout_ms"] == 1000

    deleted = await client.delete(
        f"/api/v1/admin/tenants/{tenant_id}", headers=admin_header()
    )
    assert deleted.status_code == 204
    missing_after = await client.get(
        f"/api/v1/admin/tenants/{tenant_id}", headers=admin_header()
    )
    assert missing_after.status_code == 404


async def test_api_key_create_list_and_revoke(api: ApiContext) -> None:
    client = api.client
    headers = auth_header(api.seeded.key)

    created = await client.post(
        "/api/v1/api-keys", headers=headers, json={"name": "ci"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["key"].startswith(body["key_prefix"])
    key_id = body["id"]

    listed = await client.get("/api/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    assert all("key" not in item for item in listed.json())
    assert key_id in [item["id"] for item in listed.json()]

    revoked = await client.delete(f"/api/v1/api-keys/{key_id}", headers=headers)
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None

    rejected = await client.get("/api/v1/api-keys", headers=auth_header(body["key"]))
    assert rejected.status_code == 401

    again = await client.delete(f"/api/v1/api-keys/{key_id}", headers=headers)
    assert again.status_code == 200

    missing = await client.delete(
        f"/api/v1/api-keys/{uuid4()}", headers=headers
    )
    assert missing.status_code == 404


async def test_sandbox_routes(api: ApiContext) -> None:
    client = api.client
    headers = auth_header(api.seeded.key)

    created = await client.post(
        "/api/v1/sandboxes",
        headers=headers,
        json={"image": "alpine", "vm_type": "micro", "expires_at": "2026-12-31T00:00:00Z"},
    )
    assert created.status_code == 201
    sandbox = created.json()
    sandbox_id = sandbox["id"]
    assert sandbox["status"] == "queued"

    fetched = await client.get(f"/api/v1/sandboxes/{sandbox_id}", headers=headers)
    assert fetched.status_code == 200

    listed = await client.get("/api/v1/sandboxes", headers=headers)
    assert listed.status_code == 200
    assert sandbox_id in [item["id"] for item in listed.json()]

    queued = await client.get("/api/v1/sandboxes?status=queued", headers=headers)
    assert sandbox_id in [item["id"] for item in queued.json()]
    running = await client.get("/api/v1/sandboxes?status=running", headers=headers)
    assert sandbox_id not in [item["id"] for item in running.json()]

    forked = await client.post(
        f"/api/v1/sandboxes/{sandbox_id}/fork", headers=headers, json={}
    )
    assert forked.status_code == 201
    assert forked.json()["parent_id"] == sandbox_id
    assert forked.json()["image"] == "alpine"
    assert forked.json()["vm_type"] == "micro"

    not_running = await client.post(
        f"/api/v1/sandboxes/{sandbox_id}/exec",
        headers=headers,
        json={"command": ["echo", "hi"]},
    )
    assert not_running.status_code == 409

    async with api.factory() as session:
        repository = SandboxRepository(session)
        record = await repository.get(UUID(sandbox_id), api.seeded.tenant_id)
        assert record is not None
        record.status = "running"
        record.vm_id = "vm-1"
        await repository.save(record)
        await session.commit()

    executed = await client.post(
        f"/api/v1/sandboxes/{sandbox_id}/exec",
        headers=headers,
        json={"command": ["echo", "hi"]},
    )
    assert executed.status_code == 200
    assert executed.json()["exit_code"] == 0
    assert "fake execution" in executed.json()["stdout"]

    stopped = await client.post(
        f"/api/v1/sandboxes/{sandbox_id}/stop", headers=headers
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert api.engine.stopped == ["vm-1"]

    missing = await client.get(
        f"/api/v1/sandboxes/{UUID(int=0)}", headers=headers
    )
    assert missing.status_code == 404
