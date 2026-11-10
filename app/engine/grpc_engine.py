from typing import Any

import grpc

from app.config import get_settings
from app.engine.base import EngineError, ExecResult, VmInfo
from app.engine.gen.hyper.grpc.v1 import hyper_pb2 as _hyper_pb2
from app.engine.gen.hyper.grpc.v1 import hyper_pb2_grpc as _hyper_pb2_grpc

hyper_pb2: Any = _hyper_pb2
hyper_pb2_grpc: Any = _hyper_pb2_grpc

_INSTANCE_TYPES = {
    "micro": hyper_pb2.INSTANCE_TYPE_MICRO,
    "milli": hyper_pb2.INSTANCE_TYPE_MILLI,
    "centi": hyper_pb2.INSTANCE_TYPE_CENTI,
    "deci": hyper_pb2.INSTANCE_TYPE_DECI,
    "base": hyper_pb2.INSTANCE_TYPE_BASE,
    "deca": hyper_pb2.INSTANCE_TYPE_DECA,
    "hecto": hyper_pb2.INSTANCE_TYPE_HECTO,
    "kilo": hyper_pb2.INSTANCE_TYPE_KILO,
    "mega": hyper_pb2.INSTANCE_TYPE_MEGA,
    "giga": hyper_pb2.INSTANCE_TYPE_GIGA,
    "tera": hyper_pb2.INSTANCE_TYPE_TERA,
}

_ARCHITECTURES = {
    "x86_64": hyper_pb2.ARCHITECTURE_X86_64,
    "amd64": hyper_pb2.ARCHITECTURE_X86_64,
    "aarch64": hyper_pb2.ARCHITECTURE_AARCH64,
    "arm64": hyper_pb2.ARCHITECTURE_AARCH64,
}


def _normalize_image_ref(ref: str) -> str:
    """Expand a short Docker-style image ref to a fully qualified OCI reference.

    "alpine" -> "docker.io/library/alpine:latest"
    "ghcr.io/foo/bar" -> "ghcr.io/foo/bar:latest"
    """
    ref = ref.strip()
    first, sep, rest = ref.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        registry, path = first, rest
    else:
        registry, path = "docker.io", ref
    if registry == "docker.io" and "/" not in path:
        path = f"library/{path}"
    *_, last = path.rsplit("/", 1)
    if "@" not in last and ":" not in last:
        path = f"{path}:latest"
    return f"{registry}/{path}"


class GrpcEngine:
    """gRPC adapter for the Hyper VM lifecycle service."""

    def __init__(
        self,
        *,
        target: str | None = None,
        stub: Any | None = None,
        channel: Any | None = None,
    ) -> None:
        self._settings = get_settings()
        self._image_ids: dict[str, str] = {}

        if stub is not None:
            self._channel = channel
            self._stub = stub
            return

        self._channel = self._build_channel(target or self._settings.grpc_target)
        self._stub = hyper_pb2_grpc.HyperStub(self._channel)

    def _build_channel(self, target: str) -> Any:
        if self._settings.grpc_use_tls:
            credentials = grpc.ssl_channel_credentials()
            return grpc.aio.secure_channel(target, credentials)
        return grpc.aio.insecure_channel(target)

    async def _rpc(
        self,
        method: Any,
        request: Any,
        *,
        timeout: float | None = None,
        ignore_not_found: bool = False,
    ) -> Any:
        call_timeout = self._settings.grpc_timeout_seconds if timeout is None else timeout
        try:
            return await method(request, timeout=call_timeout)
        except grpc.aio.AioRpcError as exc:
            if ignore_not_found and exc.code() == grpc.StatusCode.NOT_FOUND:
                return None
            raise EngineError(f"gRPC {exc.code().name}: {exc.details()}") from exc

    async def _ensure_image(self, image: str) -> str:
        image_ref = _normalize_image_ref(image)
        cached = self._image_ids.get(image_ref)
        if cached is not None:
            return cached

        response = await self._rpc(
            self._stub.LoadImage,
            hyper_pb2.LoadImageRequest(image_ref=image_ref),
            timeout=self._settings.grpc_image_timeout_seconds,
        )
        img_id = str(response.img_id)
        if not img_id:
            raise EngineError("LoadImage returned an empty img_id")

        self._image_ids[image_ref] = img_id
        return img_id

    def _instance_type(self, vm_type: str) -> Any:
        instance_type = _INSTANCE_TYPES.get(vm_type.strip().lower())
        if instance_type is None:
            raise EngineError(f"Unsupported vm_type: {vm_type}")
        return instance_type

    def _architecture(self) -> Any:
        architecture = _ARCHITECTURES.get(self._settings.grpc_arch.strip().lower())
        if architecture is None:
            raise EngineError(f"Unsupported grpc_arch: {self._settings.grpc_arch}")
        return architecture

    async def create_vm(
        self,
        *,
        sandbox_id: str,
        image: str,
        vm_type: str,
        idempotency_key: str,
    ) -> str:
        instance_type = self._instance_type(vm_type)
        architecture = self._architecture()
        img_id = await self._ensure_image(image)
        response = await self._rpc(
            self._stub.CreateVm,
            hyper_pb2.CreateVmRequest(
                img_id=img_id,
                instance_type=instance_type,
                arch=architecture,
                idempotency_key=idempotency_key,
            ),
        )
        vm_id = str(response.vm_id)
        if not vm_id:
            raise EngineError("CreateVm returned an empty vm_id")
        return vm_id

    async def stop_vm(self, vm_id: str, *, idempotency_key: str) -> None:
        await self._rpc(
            self._stub.StopVm,
            hyper_pb2.StopVmRequest(vm_id=vm_id),
            ignore_not_found=True,
        )

    async def execute(self, sandbox_id: str, command: tuple[str, ...]) -> ExecResult:
        response = await self._rpc(
            self._stub.Exec,
            hyper_pb2.ExecRequest(
                vm_id=sandbox_id,
                command=list(command),
                timeout_ms=self._settings.grpc_exec_timeout_ms,
            ),
        )
        return ExecResult(
            exit_code=response.exit_code,
            stdout=response.stdout,
            stderr=response.stderr,
        )

    async def list_vms(self) -> list[VmInfo]:
        vms: list[VmInfo] = []
        page_token = ""
        while True:
            response = await self._rpc(
                self._stub.ListVms,
                hyper_pb2.ListVmsRequest(page_token=page_token),
            )
            vms.extend(VmInfo(vm_id=str(vm.vm_id), node=str(vm.node)) for vm in response.vms)
            next_token = str(response.next_page_token)
            if not next_token:
                return vms
            page_token = next_token

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
