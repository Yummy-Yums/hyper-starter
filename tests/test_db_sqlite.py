import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas import ApiKeyCreate, SandboxCreate, TenantCreate
from app.repositories.api_keys import ApiKeyRepository
from app.repositories.sandboxes import SandboxRepository
from app.services.api_keys import ApiKeyService
from app.services.quota import QuotaExceeded
from app.services.sandboxes import SandboxNotFound, SandboxService
from app.services.tenants import TenantService


async def test_tenant_and_sandbox_lifecycle(session: AsyncSession) -> None:
    tenants = TenantService(session)
    tenant = await tenants.create(TenantCreate(name="acme", max_running_sandboxes=1))
    other = await tenants.create(TenantCreate(name="other"))
    assert tenant.max_running_sandboxes == 1
    assert tenant.max_exec_timeout_ms == 60000

    sandboxes = SandboxService(session)
    expires_at = datetime(2026, 12, 31, tzinfo=UTC)
    sandbox = await sandboxes.create(
        tenant.id, SandboxCreate(image="alpine", vm_type="micro", expires_at=expires_at)
    )
    assert sandbox.status == "queued"
    assert (await sandboxes.get(sandbox.id, tenant.id)).id == sandbox.id

    with pytest.raises(QuotaExceeded):
        await sandboxes.create(
            tenant.id, SandboxCreate(image="alpine", vm_type="micro", expires_at=expires_at)
        )

    with pytest.raises(SandboxNotFound):
        await sandboxes.get(sandbox.id, other.id)

    stopped = await sandboxes.stop(sandbox.id, tenant.id)
    assert stopped.status == "stopped"
    assert stopped.stopped_at is not None

    parent = await sandboxes.create(
        tenant.id, SandboxCreate(image="alpine", vm_type="micro", expires_at=expires_at)
    )
    await sandboxes.stop(parent.id, tenant.id)
    forked = await sandboxes.create(
        tenant.id,
        SandboxCreate(
            image="alpine",
            vm_type="micro",
            expires_at=expires_at,
            parent_id=parent.id,
        ),
    )
    assert forked.parent_id == parent.id

    with pytest.raises(SandboxNotFound):
        await sandboxes.create(
            other.id,
            SandboxCreate(
                image="alpine",
                vm_type="micro",
                expires_at=expires_at,
                parent_id=forked.id,
            ),
        )


async def test_api_key_lifecycle(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    keys = ApiKeyService(session)
    created = await keys.create(tenant.id, ApiKeyCreate(name="ci"))

    assert created.key.startswith(created.key_prefix)
    assert len(created.key_prefix) == 8
    assert len(created.key) >= 43

    stored = await ApiKeyRepository(session).get(created.id, tenant.id)
    assert stored is not None
    assert stored.key_prefix == created.key_prefix
    assert stored.key_hash == hashlib.sha256(created.key.encode("utf-8")).digest()
    assert stored.key_hash != created.key.encode("utf-8")

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    first = await keys.authenticate(created.key, now=t0)
    assert first is not None
    second = await keys.authenticate(created.key, now=t0 + timedelta(seconds=30))
    assert second is not None
    assert second.last_used_at == first.last_used_at
    third = await keys.authenticate(created.key, now=t0 + timedelta(seconds=61))
    assert third is not None
    assert as_utc(third.last_used_at) == t0 + timedelta(seconds=61)

    assert await keys.authenticate("short") is None
    assert await keys.authenticate("x" * 43) is None

    await keys.revoke(created.id, tenant.id)
    assert await keys.authenticate(created.key) is None


async def test_api_key_prefix_lookup_and_hash_collisions(
    session: AsyncSession,
) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    repository = ApiKeyRepository(session)
    prefix = "abcd1234"
    first_raw = f"{prefix}-first"
    second_raw = f"{prefix}-second"

    first = await repository.create(
        tenant_id=tenant.id,
        name="first",
        key_prefix=prefix,
        key_hash=hashlib.sha256(first_raw.encode("utf-8")).digest(),
    )
    second = await repository.create(
        tenant_id=tenant.id,
        name="second",
        key_prefix=prefix,
        key_hash=hashlib.sha256(second_raw.encode("utf-8")).digest(),
    )
    await session.commit()

    active = await repository.list_by_prefix(prefix)
    assert {key.id for key in active} == {first.id, second.id}

    keys = ApiKeyService(session)
    authenticated_first = await keys.authenticate(first_raw)
    authenticated_second = await keys.authenticate(second_raw)
    assert authenticated_first is not None
    assert authenticated_second is not None
    assert authenticated_first.id == first.id
    assert authenticated_second.id == second.id
    assert await keys.authenticate(f"{prefix}-unknown") is None

    await keys.revoke(second.id, tenant.id)
    assert await keys.authenticate(second_raw) is None
    assert (await keys.authenticate(first_raw)).id == first.id

    remaining = await repository.list_by_prefix(prefix)
    assert [key.id for key in remaining] == [first.id]


async def test_quota_race_allows_only_one_create(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant = await TenantService(session).create(
        TenantCreate(name="race", max_running_sandboxes=1)
    )
    payload = SandboxCreate(
        image="alpine",
        vm_type="micro",
        expires_at=datetime(2026, 12, 31, tzinfo=UTC),
    )

    async def attempt() -> str:
        async with session_factory() as race_session:
            try:
                await SandboxService(race_session).create(tenant.id, payload)
            except QuotaExceeded:
                return "quota"
            return "created"

    results = await asyncio.gather(attempt(), attempt())

    assert sorted(results) == ["created", "quota"]
    assert await SandboxRepository(session).count_active(tenant.id) == 1


def as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
