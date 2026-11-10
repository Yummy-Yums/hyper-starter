from datetime import UTC, datetime
from typing import Any

import grpc
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SandboxCreate, TenantCreate
from app.config import Settings
from app.engine.base import EngineError, ExecResult, VmInfo
from app.engine.fake import FakeEngine
from app.engine.gen.hyper.grpc.v1 import hyper_pb2
from app.engine.grpc_engine import GrpcEngine, _normalize_image_ref
from app.repositories.sandboxes import SandboxRepository
from app.services.sandboxes import SandboxNotRunning, SandboxService
from app.services.tenants import TenantService


class FakeStub:
    def __init__(self) -> None:
        self.load_image_requests: list[Any] = []
        self.create_vm_requests: list[Any] = []
        self.stop_vm_requests: list[Any] = []
        self.exec_requests: list[Any] = []
        self.list_vms_requests: list[Any] = []

    async def LoadImage(self, request: Any, timeout: float | None = None) -> Any:
        self.load_image_requests.append(request)
        return hyper_pb2.LoadImageResponse(img_id="img-1")

    async def CreateVm(self, request: Any, timeout: float | None = None) -> Any:
        self.create_vm_requests.append(request)
        return hyper_pb2.CreateVmResponse(vm_id="vm-1", node="node-a")

    async def StopVm(self, request: Any, timeout: float | None = None) -> Any:
        self.stop_vm_requests.append(request)
        return hyper_pb2.StopVmResponse()

    async def Exec(self, request: Any, timeout: float | None = None) -> Any:
        self.exec_requests.append(request)
        return hyper_pb2.ExecResponse(
            exit_code=7,
            stdout=b"stdout-data",
            stderr=b"stderr-data",
        )

    async def ListVms(self, request: Any, timeout: float | None = None) -> Any:
        self.list_vms_requests.append(request)
        pages = [
            hyper_pb2.ListVmsResponse(
                vms=[
                    hyper_pb2.Vm(vm_id="vm-1", node="node-a"),
                    hyper_pb2.Vm(vm_id="vm-2", node="node-a"),
                ],
                next_page_token="cursor-1",
            ),
            hyper_pb2.ListVmsResponse(
                vms=[hyper_pb2.Vm(vm_id="vm-3", node="node-b")],
            ),
        ]
        return pages[0 if not request.page_token else 1]


class NotFoundStopStub(FakeStub):
    async def StopVm(self, request: Any, timeout: float | None = None) -> Any:
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.NOT_FOUND,
            details="vm is already gone",
        )


class FailingCreateStub(FakeStub):
    async def CreateVm(self, request: Any, timeout: float | None = None) -> Any:
        raise grpc.aio.AioRpcError(
            grpc.StatusCode.UNAVAILABLE,
            details="engine down",
        )


class RecordingEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.executed: list[tuple[str, tuple[str, ...]]] = []

    async def execute(self, sandbox_id: str, command: tuple[str, ...]) -> ExecResult:
        self.executed.append((sandbox_id, command))
        return ExecResult(exit_code=0, stdout=b"ok")


@pytest.fixture
def grpc_settings(monkeypatch) -> Settings:
    settings = Settings(
        grpc_arch="x86_64",
        grpc_timeout_seconds=5.0,
        grpc_image_timeout_seconds=10.0,
        grpc_exec_timeout_ms=1234,
    )
    monkeypatch.setattr("app.engine.grpc_engine.get_settings", lambda: settings)
    return settings


async def test_create_vm_maps_and_caches_image(grpc_settings: Settings) -> None:
    stub = FakeStub()
    engine = GrpcEngine(stub=stub)

    vm_id = await engine.create_vm(
        sandbox_id="sandbox-1",
        image="docker.io/library/alpine:3.19",
        vm_type="micro",
        idempotency_key="sandbox-1",
    )
    assert vm_id == "vm-1"
    assert len(stub.load_image_requests) == 1
    assert stub.load_image_requests[0].image_ref == "docker.io/library/alpine:3.19"

    request = stub.create_vm_requests[0]
    assert request.img_id == "img-1"
    assert request.instance_type == hyper_pb2.INSTANCE_TYPE_MICRO
    assert request.arch == hyper_pb2.ARCHITECTURE_X86_64
    assert request.idempotency_key == "sandbox-1"

    await engine.create_vm(
        sandbox_id="sandbox-2",
        image="docker.io/library/alpine:3.19",
        vm_type="milli",
        idempotency_key="sandbox-2",
    )
    assert len(stub.load_image_requests) == 1
    assert len(stub.create_vm_requests) == 2


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("alpine", "docker.io/library/alpine:latest"),
        ("  alpine  ", "docker.io/library/alpine:latest"),
        ("alpine:3.19", "docker.io/library/alpine:3.19"),
        ("library/alpine", "docker.io/library/alpine:latest"),
        ("docker.io/library/alpine:3.19", "docker.io/library/alpine:3.19"),
        ("ghcr.io/foo/bar", "ghcr.io/foo/bar:latest"),
        ("ghcr.io/foo/bar:v1", "ghcr.io/foo/bar:v1"),
        ("localhost:5000/myimg", "localhost:5000/myimg:latest"),
        (
            "alpine@sha256:abc123",
            "docker.io/library/alpine@sha256:abc123",
        ),
    ],
)
def test_normalize_image_ref(ref: str, expected: str) -> None:
    assert _normalize_image_ref(ref) == expected


async def test_short_image_ref_is_expanded(grpc_settings: Settings) -> None:
    stub = FakeStub()
    engine = GrpcEngine(stub=stub)

    await engine.create_vm(
        sandbox_id="sandbox-1",
        image="alpine",
        vm_type="micro",
        idempotency_key="sandbox-1",
    )

    assert stub.load_image_requests[0].image_ref == "docker.io/library/alpine:latest"

    await engine.create_vm(
        sandbox_id="sandbox-2",
        image="docker.io/library/alpine:latest",
        vm_type="micro",
        idempotency_key="sandbox-2",
    )
    assert len(stub.load_image_requests) == 1


async def test_unknown_vm_type_raises_engine_error(grpc_settings: Settings) -> None:
    engine = GrpcEngine(stub=FakeStub())

    with pytest.raises(EngineError, match="Unsupported vm_type"):
        await engine.create_vm(
            sandbox_id="sandbox-1",
            image="alpine",
            vm_type="unknown",
            idempotency_key="sandbox-1",
        )


async def test_stop_vm_ignores_not_found(grpc_settings: Settings) -> None:
    engine = GrpcEngine(stub=NotFoundStopStub())

    await engine.stop_vm("vm-1", idempotency_key="sandbox-1")


async def test_grpc_error_is_mapped(grpc_settings: Settings) -> None:
    engine = GrpcEngine(stub=FailingCreateStub())

    with pytest.raises(EngineError, match="UNAVAILABLE: engine down"):
        await engine.create_vm(
            sandbox_id="sandbox-1",
            image="alpine",
            vm_type="micro",
            idempotency_key="sandbox-1",
        )


async def test_execute_maps_request_and_response(grpc_settings: Settings) -> None:
    stub = FakeStub()
    engine = GrpcEngine(stub=stub)

    result = await engine.execute("vm-1", ("echo", "hello"))

    assert result == ExecResult(
        exit_code=7,
        stdout=b"stdout-data",
        stderr=b"stderr-data",
    )
    request = stub.exec_requests[0]
    assert request.vm_id == "vm-1"
    assert list(request.command) == ["echo", "hello"]
    assert request.timeout_ms == 1234


async def test_list_vms_follows_pagination(grpc_settings: Settings) -> None:
    stub = FakeStub()
    engine = GrpcEngine(stub=stub)

    vms = await engine.list_vms()

    assert vms == [
        VmInfo(vm_id="vm-1", node="node-a"),
        VmInfo(vm_id="vm-2", node="node-a"),
        VmInfo(vm_id="vm-3", node="node-b"),
    ]
    assert len(stub.list_vms_requests) == 2
    assert stub.list_vms_requests[0].page_token == ""
    assert stub.list_vms_requests[1].page_token == "cursor-1"


async def test_fake_engine_lists_running_vms() -> None:
    engine = FakeEngine()
    await engine.create_vm(
        sandbox_id="a",
        image="alpine",
        vm_type="micro",
        idempotency_key="a",
    )
    await engine.create_vm(
        sandbox_id="b",
        image="alpine",
        vm_type="micro",
        idempotency_key="b",
    )
    await engine.stop_vm("fake-a", idempotency_key="a")

    assert await engine.list_vms() == [VmInfo(vm_id="fake-b", node="fake-node")]


async def test_service_execute_passes_vm_id(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandboxes = SandboxService(session)
    sandbox = await sandboxes.create(
        tenant.id,
        SandboxCreate(
            image="alpine",
            vm_type="micro",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
        ),
    )
    repository = SandboxRepository(session)
    sandbox.status = "running"
    sandbox.vm_id = "vm-real"
    await repository.save(sandbox)
    await session.commit()

    engine = RecordingEngine()
    result = await sandboxes.execute(sandbox.id, tenant.id, ["echo", "hi"], engine)

    assert result.exit_code == 0
    assert engine.executed == [("vm-real", ("echo", "hi"))]


async def test_service_execute_requires_vm_id(session: AsyncSession) -> None:
    tenant = await TenantService(session).create(TenantCreate(name="acme"))
    sandboxes = SandboxService(session)
    sandbox = await sandboxes.create(
        tenant.id,
        SandboxCreate(
            image="alpine",
            vm_type="micro",
            expires_at=datetime(2026, 12, 31, tzinfo=UTC),
        ),
    )
    sandbox.status = "running"
    await SandboxRepository(session).save(sandbox)
    await session.commit()

    with pytest.raises(SandboxNotRunning):
        await sandboxes.execute(sandbox.id, tenant.id, ["echo"], RecordingEngine())
