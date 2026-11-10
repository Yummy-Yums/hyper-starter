from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SandboxStatus = Literal["queued", "running", "stopped", "failed"]


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    max_running_sandboxes: int = Field(default=5, ge=1)
    max_exec_timeout_ms: int = Field(default=60000, ge=1)


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    max_running_sandboxes: int | None = Field(default=None, ge=1)
    max_exec_timeout_ms: int | None = Field(default=None, ge=1)


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    max_running_sandboxes: int
    max_exec_timeout_ms: int
    created_at: datetime
    updated_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    key_prefix: str
    revoked_at: datetime | None
    last_used_at: datetime | None


class ApiKeyCreated(ApiKeyResponse):
    key: str


class SandboxCreate(BaseModel):
    image: str = Field(min_length=1, max_length=255)
    vm_type: str = Field(min_length=1, max_length=255)
    parent_id: UUID | None = None
    expires_at: datetime


class SandboxFork(BaseModel):
    image: str | None = Field(default=None, min_length=1, max_length=255)
    vm_type: str | None = Field(default=None, min_length=1, max_length=255)
    expires_at: datetime | None = None


class SandboxExec(BaseModel):
    command: list[str] = Field(min_length=1)


class SandboxExecResponse(BaseModel):
    sandbox_id: UUID
    exit_code: int
    stdout: str
    stderr: str


class SandboxResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    parent_id: UUID | None
    vm_id: str | None
    image: str
    vm_type: str
    status: SandboxStatus
    expires_at: datetime
    last_active_at: datetime | None
    stopped_at: datetime | None
    created_at: datetime
    updated_at: datetime
