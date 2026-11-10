from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TenantCreate, TenantUpdate
from app.db.models import Tenant
from app.repositories.tenants import TenantRepository


class TenantNotFound(Exception):
    pass


class TenantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TenantRepository(session)

    async def create(self, payload: TenantCreate) -> Tenant:
        tenant = await self.repository.create(payload)
        await self.session.commit()
        return tenant

    async def get(self, tenant_id: UUID) -> Tenant:
        tenant = await self.repository.get(tenant_id)
        if tenant is None:
            raise TenantNotFound(tenant_id)
        return tenant

    async def list(self) -> list[Tenant]:
        return await self.repository.list()

    async def update(self, tenant_id: UUID, payload: TenantUpdate) -> Tenant:
        tenant = await self.get(tenant_id)
        tenant = await self.repository.update(tenant, payload)
        await self.session.commit()
        return tenant

    async def delete(self, tenant_id: UUID) -> None:
        tenant = await self.get(tenant_id)
        await self.repository.delete(tenant)
        await self.session.commit()
