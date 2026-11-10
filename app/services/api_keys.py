import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiKeyCreate, ApiKeyCreated
from app.db.models import ApiKey
from app.repositories.api_keys import ApiKeyRepository
from app.repositories.tenants import TenantRepository
from app.services.tenants import TenantNotFound

LAST_USED_TOUCH_INTERVAL = timedelta(minutes=1)

class ApiKeyNotFound(Exception):
    pass

class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ApiKeyRepository(session)
        self.tenants = TenantRepository(session)

    def _generate(self) -> tuple[str, str, bytes]:
        key = secrets.token_urlsafe(32)
        key_prefix = key[:8]
        key_hash = hashlib.sha256(key.encode("utf-8")).digest()
        return key, key_prefix, key_hash

    async def create(self, tenant_id: UUID, payload: ApiKeyCreate) -> ApiKeyCreated:
        if await self.tenants.get(tenant_id) is None:
            raise TenantNotFound(tenant_id)

        key, key_prefix, key_hash = self._generate()
        api_key = await self.repository.create(
            tenant_id=tenant_id,
            name=payload.name,
            key_prefix=key_prefix,
            key_hash=key_hash,
        )
        await self.session.commit()
        return ApiKeyCreated(
            id=api_key.id,
            tenant_id=api_key.tenant_id,
            name=api_key.name,
            key_prefix=api_key.key_prefix,
            revoked_at=api_key.revoked_at,
            last_used_at=api_key.last_used_at,
            key=key,
        )

    async def list(self, tenant_id: UUID) -> list[ApiKey]:
        return await self.repository.list_by_tenant(tenant_id)

    async def revoke(self, key_id: UUID, tenant_id: UUID) -> ApiKey:
        api_key = await self.repository.get(key_id, tenant_id)
        if api_key is None:
            raise ApiKeyNotFound(key_id)
        if api_key.revoked_at is None:
            api_key = await self.repository.revoke(
                api_key, datetime.now(UTC)
            )
            await self.session.commit()
        return api_key

    async def authenticate(
        self, raw_key: str, *, now: datetime | None = None
    ) -> ApiKey | None:
        if len(raw_key) < 8:
            return None

        expected_hash = hashlib.sha256(raw_key.encode("utf-8")).digest()
        candidates = await self.repository.list_by_prefix(raw_key[:8])
        for candidate in candidates:
            if hmac.compare_digest(candidate.key_hash, expected_hash):
                touched_at = now or datetime.now(UTC)
                last_used = candidate.last_used_at
                if last_used is not None and last_used.tzinfo is None:
                    last_used = last_used.replace(tzinfo=UTC)
                if last_used is None or touched_at - last_used >= LAST_USED_TOUCH_INTERVAL:
                    await self.repository.touch_last_used(candidate, touched_at)
                    await self.session.commit()
                return candidate
        return None
