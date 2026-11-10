from app.engine.base import EngineError, ExecResult


class GrpcEngine:
    """Production gRPC adapter placeholder; implement against generated Hyper stubs."""

    async def create_vm(
        self,
        *,
        sandbox_id: str,
        image: str,
        vm_type: str,
        idempotency_key: str,
    ) -> str:
        raise EngineError("gRPC engine adapter is not configured yet")

    async def stop_vm(self, vm_id: str, *, idempotency_key: str) -> None:
        raise EngineError("gRPC engine adapter is not configured yet")

    async def execute(self, sandbox_id: str, command: tuple[str, ...]) -> ExecResult:
        raise EngineError("gRPC engine adapter is not configured yet")
