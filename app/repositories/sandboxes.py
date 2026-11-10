import builtins
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SandboxRecord


class SandboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID | None,
        image: str,
        vm_type: str,
        expires_at: datetime,
        status: str = "queued",
    ) -> SandboxRecord:
        sandbox = SandboxRecord(
            tenant_id=tenant_id,
            parent_id=parent_id,
            image=image,
            vm_type=vm_type,
            status=status,
            expires_at=expires_at,
        )
        self.session.add(sandbox)
        await self.session.flush()
        await self.session.refresh(sandbox)
        return sandbox

    async def get(self, sandbox_id: UUID, tenant_id: UUID) -> SandboxRecord | None:
        result = await self.session.execute(
            select(SandboxRecord).where(
                SandboxRecord.id == sandbox_id,
                SandboxRecord.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list(self, tenant_id: UUID, status: str | None = None) -> list[SandboxRecord]:
        query = select(SandboxRecord).where(SandboxRecord.tenant_id == tenant_id)
        if status is not None:
            query = query.where(SandboxRecord.status == status)
        result = await self.session.execute(query.order_by(SandboxRecord.created_at.desc()))
        return list(result.scalars().all())

    async def count_active(self, tenant_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(SandboxRecord)
            .where(
                SandboxRecord.tenant_id == tenant_id,
                SandboxRecord.status.in_(("queued", "running")),
            )
        )
        return int(result.scalar_one())

    async def save(self, sandbox: SandboxRecord) -> SandboxRecord:
        await self.session.flush()
        await self.session.refresh(sandbox)
        return sandbox

    async def list_queued_for_reconcile(self, limit: int) -> builtins.list[SandboxRecord]:
        result = await self.session.execute(
            select(SandboxRecord)
            .where(SandboxRecord.status == "queued")
            .order_by(SandboxRecord.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def list_reapable(
        self,
        *,
        now: datetime,
        idle_cutoff: datetime,
        limit: int,
    ) -> builtins.list[SandboxRecord]:
        result = await self.session.execute(
            select(SandboxRecord)
            .where(
                SandboxRecord.status.in_(("queued", "running")),
                or_(
                    SandboxRecord.expires_at <= now,
                    and_(
                        SandboxRecord.status == "running",
                        func.coalesce(
                            SandboxRecord.last_active_at, SandboxRecord.created_at
                        )
                        <= idle_cutoff,
                    ),
                ),
            )
            .order_by(SandboxRecord.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())
