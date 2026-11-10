from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TenantCreate
from app.engine.base import EngineError
from app.engine.fake import FakeEngine
from app.repositories.sandboxes import SandboxRepository
from app.services.tenants import TenantService
from app.workers.reaper import run_reaper_once
from app.workers.reconciler import reconcile_once

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class FailingCreateEngine(FakeEngine):
    async def create_vm(
        self,
        *,
        sandbox_id: str,
        image: str,
        vm_type: str,
        idempotency_key: str,
    ) -> str:
        raise EngineError("create failed")


class FailingStopEngine(FakeEngine):
    async def stop_vm(self, vm_id: str, *, idempotency_key: str) -> None:
        raise EngineError("stop failed")


async def add_sandbox(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    status: str = "queued",
    vm_id: str | None = None,
    expires_at: datetime = NOW + timedelta(hours=1),
    last_active_at: datetime | None = None,
) -> UUID:
    repository = SandboxRepository(session)
    sandbox = await repository.create(
        tenant_id=tenant_id,
        parent_id=None,
        image="alpine",
        vm_type="micro",
        expires_at=expires_at,
        status=status,
    )
    sandbox.vm_id = vm_id
    sandbox.last_active_at = last_active_at
    await repository.save(sandbox)
    await session.commit()
    return sandbox.id


async def test_engine_create_and_stop_are_idempotent() -> None:
    engine = FakeEngine()

    first = await engine.create_vm(
        sandbox_id="sandbox-1",
        image="alpine",
        vm_type="micro",
        idempotency_key="sandbox-1",
    )
    second = await engine.create_vm(
        sandbox_id="sandbox-1",
        image="alpine",
        vm_type="micro",
        idempotency_key="sandbox-1",
    )
    assert first == second
    assert len(engine.created) == 1

    await engine.stop_vm(first, idempotency_key="sandbox-1")
    await engine.stop_vm(first, idempotency_key="sandbox-1")
    assert engine.stopped == [first]


async def test_reconciler_reuses_vm_after_retry(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandbox_id = await add_sandbox(session, tenant.id)
    engine = FakeEngine()

    existing_vm = await engine.create_vm(
        sandbox_id=str(sandbox_id),
        image="alpine",
        vm_type="micro",
        idempotency_key=str(sandbox_id),
    )
    changed = await reconcile_once(session, engine)

    sandbox = await SandboxRepository(session).get(sandbox_id, tenant.id)
    assert changed == 1
    assert sandbox is not None
    assert sandbox.vm_id == existing_vm
    assert len(engine.created) == 1


async def test_reconciler_creates_vm_and_advances_status(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandbox_id = await add_sandbox(session, tenant.id)
    engine = FakeEngine()

    changed = await reconcile_once(session, engine)

    sandbox = await SandboxRepository(session).get(sandbox_id, tenant.id)
    assert changed == 1
    assert sandbox is not None
    assert sandbox.vm_id == f"fake-{sandbox_id}"
    assert sandbox.status == "running"
    assert sandbox.failure_reason is None
    assert engine.created[sandbox.vm_id] == ("alpine", "micro")
    assert await reconcile_once(session, engine) == 0


async def test_reconciler_marks_failed_when_engine_fails(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandbox_id = await add_sandbox(session, tenant.id)

    changed = await reconcile_once(session, FailingCreateEngine())

    sandbox = await SandboxRepository(session).get(sandbox_id, tenant.id)
    assert changed == 1
    assert sandbox is not None
    assert sandbox.status == "failed"
    assert sandbox.vm_id is None
    assert sandbox.failure_reason == "create failed"


async def test_reaper_stops_expired_sandbox(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandbox_id = await add_sandbox(
        session,
        tenant.id,
        status="running",
        vm_id="vm-1",
        expires_at=NOW - timedelta(seconds=1),
        last_active_at=NOW,
    )
    engine = FakeEngine()

    changed = await run_reaper_once(session, engine, now=NOW)

    sandbox = await SandboxRepository(session).get(sandbox_id, tenant.id)
    assert changed == 1
    assert sandbox is not None
    assert sandbox.status == "stopped"
    assert sandbox.stopped_at is not None
    assert engine.stopped == ["vm-1"]
    assert await run_reaper_once(session, engine, now=NOW) == 0


async def test_reaper_stops_idle_sandbox(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    idle_id = await add_sandbox(
        session,
        tenant.id,
        status="running",
        vm_id="vm-idle",
        last_active_at=NOW - timedelta(seconds=61),
    )
    active_id = await add_sandbox(
        session,
        tenant.id,
        status="running",
        vm_id="vm-active",
        last_active_at=NOW - timedelta(seconds=30),
    )
    engine = FakeEngine()

    changed = await run_reaper_once(
        session, engine, now=NOW, idle_timeout_seconds=60
    )

    idle = await SandboxRepository(session).get(idle_id, tenant.id)
    active = await SandboxRepository(session).get(active_id, tenant.id)
    assert changed == 1
    assert idle is not None and idle.status == "stopped"
    assert active is not None and active.status == "running"
    assert engine.stopped == ["vm-idle"]


async def test_reaper_stops_expired_queued_sandbox_without_vm(
    session: AsyncSession,
) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandbox_id = await add_sandbox(
        session,
        tenant.id,
        status="queued",
        expires_at=NOW - timedelta(seconds=1),
    )
    engine = FakeEngine()

    changed = await run_reaper_once(session, engine, now=NOW)

    sandbox = await SandboxRepository(session).get(sandbox_id, tenant.id)
    assert changed == 1
    assert sandbox is not None
    assert sandbox.status == "stopped"
    assert engine.stopped == []


async def test_reaper_leaves_sandbox_running_when_stop_fails(
    session: AsyncSession,
) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandbox_id = await add_sandbox(
        session,
        tenant.id,
        status="running",
        vm_id="vm-1",
        expires_at=NOW - timedelta(seconds=1),
    )

    changed = await run_reaper_once(session, FailingStopEngine(), now=NOW)

    sandbox = await SandboxRepository(session).get(sandbox_id, tenant.id)
    assert changed == 0
    assert sandbox is not None
    assert sandbox.status == "running"
    assert sandbox.stopped_at is None
    assert sandbox.failure_reason == "reaper stop failed: stop failed"
