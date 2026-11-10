from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session
from app.engine.base import Engine
from app.engine.fake import FakeEngine
from app.services.api_keys import ApiKeyService
from app.services.sandboxes import SandboxService
from app.services.tenants import TenantService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def settings_dependency() -> Settings:
    return get_settings()


@lru_cache
def get_engine() -> Engine:
    if get_settings().engine_backend == "grpc":
        from app.engine.grpc_engine import GrpcEngine

        return GrpcEngine()
    return FakeEngine()


EngineDep = Annotated[Engine, Depends(get_engine)]


def get_tenant_service(session: SessionDep) -> TenantService:
    return TenantService(session)


def get_api_key_service(session: SessionDep) -> ApiKeyService:
    return ApiKeyService(session)


def get_sandbox_service(session: SessionDep) -> SandboxService:
    return SandboxService(session)
