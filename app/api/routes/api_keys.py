from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.auth import AuthContextDep
from app.api.deps import get_api_key_service
from app.api.rate_limit import limiter, rate_limit_value
from app.api.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse
from app.db.models import ApiKey
from app.services.api_keys import ApiKeyNotFound, ApiKeyService
from app.services.tenants import TenantNotFound

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

ApiKeyServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
@limiter.limit(rate_limit_value)
async def create_api_key(
    request: Request,
    auth: AuthContextDep,
    payload: ApiKeyCreate,
    service: ApiKeyServiceDep,
) -> ApiKeyCreated:
    try:
        return await service.create(auth.tenant_id, payload)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant not found") from exc


@router.get("", response_model=list[ApiKeyResponse])
@limiter.limit(rate_limit_value)
async def list_api_keys(
    request: Request,
    auth: AuthContextDep,
    service: ApiKeyServiceDep,
) -> list[ApiKey]:
    return await service.list(auth.tenant_id)


@router.delete("/{key_id}", response_model=ApiKeyResponse)
@limiter.limit(rate_limit_value)
async def revoke_api_key(
    request: Request,
    key_id: UUID,
    auth: AuthContextDep,
    service: ApiKeyServiceDep,
) -> ApiKey:
    try:
        return await service.revoke(key_id, auth.tenant_id)
    except ApiKeyNotFound as exc:
        raise HTTPException(status_code=404, detail="API key not found") from exc
