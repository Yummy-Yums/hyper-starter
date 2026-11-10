from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.auth import AuthContextDep
from app.api.deps import EngineDep, get_sandbox_service
from app.api.rate_limit import limiter, rate_limit_value
from app.api.schemas import (
    SandboxCreate,
    SandboxExec,
    SandboxExecResponse,
    SandboxFork,
    SandboxResponse,
    SandboxStatus,
)
from app.db.models import SandboxRecord
from app.engine.base import EngineError
from app.services.quota import QuotaExceeded
from app.services.sandboxes import (
    SandboxNotFound,
    SandboxNotRunning,
    SandboxService,
)
from app.services.tenants import TenantNotFound

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])

SandboxServiceDep = Annotated[SandboxService, Depends(get_sandbox_service)]


@router.post("", response_model=SandboxResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(rate_limit_value)
async def create_sandbox(
    request: Request,
    auth: AuthContextDep,
    payload: SandboxCreate,
    service: SandboxServiceDep,
) -> SandboxRecord:
    try:
        return await service.create(auth.tenant_id, payload)
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant not found") from exc
    except SandboxNotFound as exc:
        raise HTTPException(status_code=404, detail="Parent sandbox not found") from exc
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail="Sandbox quota exceeded") from exc


@router.get("", response_model=list[SandboxResponse])
@limiter.limit(rate_limit_value)
async def list_sandboxes(
    request: Request,
    auth: AuthContextDep,
    service: SandboxServiceDep,
    status_filter: Annotated[SandboxStatus | None, Query(alias="status")] = None,
) -> list[SandboxRecord]:
    return await service.list(auth.tenant_id, status_filter)


@router.get("/{sandbox_id}", response_model=SandboxResponse)
@limiter.limit(rate_limit_value)
async def get_sandbox(
    request: Request,
    sandbox_id: UUID,
    auth: AuthContextDep,
    service: SandboxServiceDep,
) -> SandboxRecord:
    try:
        return await service.get(sandbox_id, auth.tenant_id)
    except SandboxNotFound as exc:
        raise HTTPException(status_code=404, detail="Sandbox not found") from exc


@router.post(
    "/{sandbox_id}/fork",
    response_model=SandboxResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(rate_limit_value)
async def fork_sandbox(
    request: Request,
    sandbox_id: UUID,
    auth: AuthContextDep,
    payload: SandboxFork,
    service: SandboxServiceDep,
) -> SandboxRecord:
    try:
        return await service.fork(sandbox_id, auth.tenant_id, payload)
    except SandboxNotFound as exc:
        raise HTTPException(status_code=404, detail="Sandbox not found") from exc
    except TenantNotFound as exc:
        raise HTTPException(status_code=404, detail="Tenant not found") from exc
    except QuotaExceeded as exc:
        raise HTTPException(status_code=429, detail="Sandbox quota exceeded") from exc


@router.post("/{sandbox_id}/exec", response_model=SandboxExecResponse)
@limiter.limit(rate_limit_value)
async def exec_sandbox(
    request: Request,
    sandbox_id: UUID,
    auth: AuthContextDep,
    payload: SandboxExec,
    service: SandboxServiceDep,
    engine: EngineDep,
) -> SandboxExecResponse:
    try:
        result = await service.execute(
            sandbox_id,
            auth.tenant_id,
            payload.command,
            engine,
        )
    except SandboxNotFound as exc:
        raise HTTPException(status_code=404, detail="Sandbox not found") from exc
    except SandboxNotRunning as exc:
        raise HTTPException(status_code=409, detail="Sandbox is not running") from exc
    except EngineError as exc:
        raise HTTPException(
            status_code=503, detail="Sandbox engine unavailable"
        ) from exc

    return SandboxExecResponse(
        sandbox_id=sandbox_id,
        exit_code=result.exit_code,
        stdout=result.stdout.decode("utf-8", errors="replace"),
        stderr=result.stderr.decode("utf-8", errors="replace"),
    )


@router.post("/{sandbox_id}/stop", response_model=SandboxResponse)
@limiter.limit(rate_limit_value)
async def stop_sandbox(
    request: Request,
    sandbox_id: UUID,
    auth: AuthContextDep,
    service: SandboxServiceDep,
    engine: EngineDep,
) -> SandboxRecord:
    try:
        return await service.stop(sandbox_id, auth.tenant_id, engine=engine)
    except SandboxNotFound as exc:
        raise HTTPException(status_code=404, detail="Sandbox not found") from exc
    except EngineError as exc:
        raise HTTPException(
            status_code=503, detail="Sandbox engine unavailable"
        ) from exc
