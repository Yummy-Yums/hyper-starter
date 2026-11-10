from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TenantCreate, TenantUpdate
from app.db.models import Tenant


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: TenantCreate) -> Tenant:
        tenant = Tenant(**payload.model_dump())
        self.session.add(tenant)
        await self.session.flush()
        await self.session.refresh(tenant)
        return tenant

    async def get(self, tenant_id: UUID) -> Tenant | None:
        return await self.session.get(Tenant, tenant_id)

    async def get_for_update(self, tenant_id: UUID) -> Tenant | None:
        await self.session.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(name=Tenant.name, updated_at=Tenant.updated_at)
        )
        result = await self.session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list(self) -> list[Tenant]:
        result = await self.session.execute(select(Tenant).order_by(Tenant.name))
        return list(result.scalars().all())

    async def update(self, tenant: Tenant, payload: TenantUpdate) -> Tenant:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(tenant, field, value)
        await self.session.flush()
        await self.session.refresh(tenant)
        return tenant

    async def delete(self, tenant: Tenant) -> None:
        await self.session.delete(tenant)
        await self.session.flush()
