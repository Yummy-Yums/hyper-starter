from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey


class ApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        name: str,
        key_prefix: str,
        key_hash: bytes,
    ) -> ApiKey:
        api_key = ApiKey(
            tenant_id=tenant_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        self.session.add(api_key)
        await self.session.flush()
        await self.session.refresh(api_key)
        return api_key

    async def get(self, key_id: UUID, tenant_id: UUID) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def list_by_tenant(self, tenant_id: UUID) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey)
            .where(ApiKey.tenant_id == tenant_id)
            .order_by(ApiKey.name)
        )
        return list(result.scalars().all())

    async def list_by_prefix(self, key_prefix: str) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(
                ApiKey.key_prefix == key_prefix,
                ApiKey.revoked_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def revoke(self, api_key: ApiKey, revoked_at: datetime) -> ApiKey:
        api_key.revoked_at = revoked_at
        await self.session.flush()
        await self.session.refresh(api_key)
        return api_key

    async def touch_last_used(self, api_key: ApiKey, used_at: datetime) -> ApiKey:
        api_key.last_used_at = used_at
        await self.session.flush()
        await self.session.refresh(api_key)
        return api_key
