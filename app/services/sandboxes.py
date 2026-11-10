import builtins
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SandboxCreate, SandboxFork
from app.db.models import SandboxRecord
from app.engine.base import Engine, EngineError, ExecResult
from app.repositories.sandboxes import SandboxRepository
from app.repositories.tenants import TenantRepository
from app.services.quota import QuotaService
from app.services.tenants import TenantNotFound


class SandboxNotFound(Exception):
    pass


class SandboxNotRunning(Exception):
    pass


class SandboxService:
    def __init__(self, session: AsyncSession, quota: QuotaService | None = None) -> None:
        self.session = session
        self.repository = SandboxRepository(session)
        self.tenants = TenantRepository(session)
        self.quota = quota or QuotaService()

    async def create(self, tenant_id: UUID, payload: SandboxCreate) -> SandboxRecord:
        tenant = await self.tenants.get_for_update(tenant_id)
        if tenant is None:
            raise TenantNotFound(tenant_id)

        if payload.parent_id is not None:
            parent = await self.repository.get(payload.parent_id, tenant_id)
            if parent is None:
                raise SandboxNotFound(payload.parent_id)

        active = await self.repository.count_active(tenant_id)
        self.quota.ensure_capacity(current=active, limit=tenant.max_running_sandboxes)

        sandbox = await self.repository.create(
            tenant_id=tenant_id,
            parent_id=payload.parent_id,
            image=payload.image,
            vm_type=payload.vm_type,
            expires_at=payload.expires_at,
        )
        await self.session.commit()
        return sandbox

    async def get(self, sandbox_id: UUID, tenant_id: UUID) -> SandboxRecord:
        sandbox = await self.repository.get(sandbox_id, tenant_id)
        if sandbox is None:
            raise SandboxNotFound(sandbox_id)
        return sandbox

    async def list(self, tenant_id: UUID, status: str | None = None) -> list[SandboxRecord]:
        return await self.repository.list(tenant_id, status)

    async def fork(
        self, parent_id: UUID, tenant_id: UUID, payload: SandboxFork
    ) -> SandboxRecord:
        parent = await self.get(parent_id, tenant_id)
        return await self.create(
            tenant_id,
            SandboxCreate(
                image=payload.image or parent.image,
                vm_type=payload.vm_type or parent.vm_type,
                parent_id=parent.id,
                expires_at=payload.expires_at or parent.expires_at,
            ),
        )

    async def stop(
        self,
        sandbox_id: UUID,
        tenant_id: UUID,
        *,
        engine: Engine | None = None,
    ) -> SandboxRecord:
        sandbox = await self.get(sandbox_id, tenant_id)
        if sandbox.status in ("stopped", "failed"):
            return sandbox

        if engine is not None and sandbox.vm_id is not None:
            try:
                await engine.stop_vm(
                    sandbox.vm_id,
                    idempotency_key=str(sandbox.id),
                )
            except EngineError as exc:
                sandbox.failure_reason = f"stop failed: {exc}"
                await self.repository.save(sandbox)
                await self.session.commit()
                raise

        sandbox.status = "stopped"
        sandbox.stopped_at = datetime.now(UTC)
        sandbox.failure_reason = None
        sandbox = await self.repository.save(sandbox)
        await self.session.commit()
        return sandbox

    async def execute(
        self,
        sandbox_id: UUID,
        tenant_id: UUID,
        command: builtins.list[str],
        engine: Engine,
    ) -> ExecResult:
        sandbox = await self.get(sandbox_id, tenant_id)
        if sandbox.status != "running":
            raise SandboxNotRunning(sandbox_id)

        result = await engine.execute(str(sandbox.id), tuple(command))
        sandbox.last_active_at = datetime.now(UTC)
        sandbox = await self.repository.save(sandbox)
        await self.session.commit()
        return result

    async def touch_active(self, sandbox_id: UUID, tenant_id: UUID) -> SandboxRecord:
        sandbox = await self.get(sandbox_id, tenant_id)
        sandbox.last_active_at = datetime.now(UTC)
        sandbox = await self.repository.save(sandbox)
        await self.session.commit()
        return sandbox
