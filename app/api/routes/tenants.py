from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.admin import require_admin
from app.api.deps import get_tenant_service
from app.api.schemas import TenantCreate, TenantResponse, TenantUpdate
from app.db.models import Tenant
from app.services.tenants import TenantNotFound, TenantService

router = APIRouter(
    prefix="/admin/tenants",
    tags=["admin:tenants"],
    dependencies=[Depends(require_admin)],
)

TenantServiceDep = Annotated[TenantService, Depends(get_tenant_service)]


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate, service: TenantServiceDep
) -> Tenant:
    return await service.create(payload)


@router.get("", response_model=list[TenantResponse])
async def list_tenants(service: TenantServiceDep) -> list[Tenant]:
    return await service.list()


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: UUID, service: TenantServiceDep) -> Tenant:
    try:
        return await service.get(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant not found") from exc


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: UUID, payload: TenantUpdate, service: TenantServiceDep
) -> Tenant:
    try:
        return await service.update(tenant_id, payload)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant not found") from exc


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(tenant_id: UUID, service: TenantServiceDep) -> None:
    try:
        await service.delete(tenant_id)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant not found") from exc
