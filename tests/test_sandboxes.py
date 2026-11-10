from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.auth import AuthContext, get_auth_context
from app.api.deps import get_sandbox_service
from app.api.schemas import SandboxCreate, SandboxResponse
from app.main import app
from app.services.sandboxes import SandboxNotFound


class FakeSandboxService:
    def __init__(self) -> None:
        self.items: dict[tuple[UUID, UUID], SandboxResponse] = {}

    async def create(self, tenant_id: UUID, payload: SandboxCreate) -> SandboxResponse:
        now = datetime.now(UTC)
        sandbox = SandboxResponse(
            id=uuid4(),
            tenant_id=tenant_id,
            parent_id=payload.parent_id,
            vm_id=None,
            image=payload.image,
            vm_type=payload.vm_type,
            status="queued",
            expires_at=payload.expires_at,
            last_active_at=None,
            stopped_at=None,
            created_at=now,
            updated_at=now,
        )
        self.items[(tenant_id, sandbox.id)] = sandbox
        return sandbox

    async def get(self, sandbox_id: UUID, tenant_id: UUID) -> SandboxResponse:
        try:
            return self.items[(tenant_id, sandbox_id)]
        except KeyError as exc:
            raise SandboxNotFound(sandbox_id) from exc


def test_create_and_get_sandbox() -> None:
    fake = FakeSandboxService()
    tenant_id = uuid4()
    auth = AuthContext(tenant_id=tenant_id, api_key_id=uuid4())
    app.dependency_overrides[get_sandbox_service] = lambda: fake
    app.dependency_overrides[get_auth_context] = lambda: auth
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/sandboxes",
                json={
                    "image": "alpine",
                    "vm_type": "micro",
                    "expires_at": "2026-10-30T00:00:00Z",
                },
            )
            assert created.status_code == 201
            body = created.json()
            sandbox_id = body["id"]
            assert str(UUID(sandbox_id)) == sandbox_id
            assert "name" not in body

            fetched = client.get(f"/api/v1/sandboxes/{sandbox_id}")
            assert fetched.status_code == 200
            assert fetched.json()["image"] == "alpine"
    finally:
        app.dependency_overrides.clear()


def test_missing_sandbox_returns_404() -> None:
    fake = FakeSandboxService()
    auth = AuthContext(tenant_id=uuid4(), api_key_id=uuid4())
    app.dependency_overrides[get_sandbox_service] = lambda: fake
    app.dependency_overrides[get_auth_context] = lambda: auth
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/sandboxes/{uuid4()}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_invalid_sandbox_id_returns_422() -> None:
    fake = FakeSandboxService()
    auth = AuthContext(tenant_id=uuid4(), api_key_id=uuid4())
    app.dependency_overrides[get_sandbox_service] = lambda: fake
    app.dependency_overrides[get_auth_context] = lambda: auth
    try:
        with TestClient(app) as client:
            fetched = client.get("/api/v1/sandboxes/not-a-uuid")
            forked = client.post("/api/v1/sandboxes/not-a-uuid/fork", json={})
            stopped = client.post("/api/v1/sandboxes/not-a-uuid/stop")
    finally:
        app.dependency_overrides.clear()

    assert fetched.status_code == 422
    assert forked.status_code == 422
    assert stopped.status_code == 422
