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
from app.services.api_keys import ApiKeyService
from app.services.tenants import TenantService


@dataclass(frozen=True)
class Seeded:
    tenant_a: UUID
    key_a: str
    tenant_b: UUID
    key_b: str
    revoked_key: str


@pytest_asyncio.fixture
async def api(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, Seeded]]:
    async with session_factory() as session:
        tenants = TenantService(session)
        tenant_a = await tenants.create(TenantCreate(name="tenant-a"))
        tenant_b = await tenants.create(TenantCreate(name="tenant-b"))

        keys = ApiKeyService(session)
        key_a = await keys.create(tenant_a.id, ApiKeyCreate(name="a"))
        key_b = await keys.create(tenant_b.id, ApiKeyCreate(name="b"))
        revoked = await keys.create(tenant_a.id, ApiKeyCreate(name="revoked"))
        await keys.revoke(revoked.id, tenant_a.id)

        seeded = Seeded(
            tenant_a=tenant_a.id,
            key_a=key_a.key,
            tenant_b=tenant_b.id,
            key_b=key_b.key,
            revoked_key=revoked.key,
        )

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_engine] = lambda: FakeEngine()
    limiter.reset()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, seeded

    app.dependency_overrides.clear()
    limiter.reset()


def auth_header(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def test_missing_or_invalid_key_returns_401(
    api: tuple[httpx.AsyncClient, Seeded],
) -> None:
    client, seeded = api
    payload = {"image": "alpine", "vm_type": "micro", "expires_at": "2026-12-31T00:00:00Z"}

    missing = await client.post("/api/v1/sandboxes", json=payload)
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    invalid = await client.post(
        "/api/v1/sandboxes", json=payload, headers=auth_header("not-a-valid-key")
    )
    assert invalid.status_code == 401

    revoked = await client.post(
        "/api/v1/sandboxes", json=payload, headers=auth_header(seeded.revoked_key)
    )
    assert revoked.status_code == 401


async def test_valid_key_attaches_tenant_id(
    api: tuple[httpx.AsyncClient, Seeded],
) -> None:
    client, seeded = api
    created = await client.post(
        "/api/v1/sandboxes",
        headers=auth_header(seeded.key_a),
        json={"image": "alpine", "vm_type": "micro", "expires_at": "2026-12-31T00:00:00Z"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["tenant_id"] == str(seeded.tenant_a)

    fetched = await client.get(
        f"/api/v1/sandboxes/{body['id']}", headers=auth_header(seeded.key_a)
    )
    assert fetched.status_code == 200


async def test_tenant_cannot_read_another_tenants_sandbox(
    api: tuple[httpx.AsyncClient, Seeded],
) -> None:
    client, seeded = api
    created = await client.post(
        "/api/v1/sandboxes",
        headers=auth_header(seeded.key_a),
        json={"image": "alpine", "vm_type": "micro", "expires_at": "2026-12-31T00:00:00Z"},
    )
    sandbox_id = created.json()["id"]

    fetched = await client.get(
        f"/api/v1/sandboxes/{sandbox_id}", headers=auth_header(seeded.key_b)
    )
    assert fetched.status_code == 404

    listed = await client.get("/api/v1/sandboxes", headers=auth_header(seeded.key_b))
    assert listed.status_code == 200
    assert listed.json() == []

    forked = await client.post(
        f"/api/v1/sandboxes/{sandbox_id}/fork",
        headers=auth_header(seeded.key_b),
        json={},
    )
    assert forked.status_code == 404

    stopped = await client.post(
        f"/api/v1/sandboxes/{sandbox_id}/stop",
        headers=auth_header(seeded.key_b),
    )
    assert stopped.status_code == 404


async def test_tenant_cannot_manage_another_tenants_api_keys(
    api: tuple[httpx.AsyncClient, Seeded],
) -> None:
    client, seeded = api
    created = await client.post(
        "/api/v1/api-keys",
        headers=auth_header(seeded.key_a),
        json={"name": "isolated"},
    )
    assert created.status_code == 201
    key_id = created.json()["id"]

    listed = await client.get(
        "/api/v1/api-keys", headers=auth_header(seeded.key_b)
    )
    assert listed.status_code == 200
    assert key_id not in [item["id"] for item in listed.json()]

    revoked = await client.delete(
        f"/api/v1/api-keys/{key_id}", headers=auth_header(seeded.key_b)
    )
    assert revoked.status_code == 404

    still_active = await client.get(
        "/api/v1/api-keys", headers=auth_header(seeded.key_a)
    )
    matching = [item for item in still_active.json() if item["id"] == key_id]
    assert len(matching) == 1
    assert matching[0]["revoked_at"] is None


async def test_rate_limit_is_per_tenant(
    api: tuple[httpx.AsyncClient, Seeded], monkeypatch
) -> None:
    client, seeded = api
    monkeypatch.setattr(
        "app.api.rate_limit.get_settings",
        lambda: Settings(rate_limit_per_minute=2),
    )
    limiter.reset()

    sandbox_id = uuid4()
    for _ in range(2):
        response = await client.get(
            f"/api/v1/sandboxes/{sandbox_id}", headers=auth_header(seeded.key_a)
        )
        assert response.status_code == 404

    limited = await client.get(
        f"/api/v1/sandboxes/{sandbox_id}", headers=auth_header(seeded.key_a)
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"

    other_tenant = await client.get(
        f"/api/v1/sandboxes/{sandbox_id}", headers=auth_header(seeded.key_b)
    )
    assert other_tenant.status_code == 404
