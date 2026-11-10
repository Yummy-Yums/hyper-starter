from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExecResult:
    exit_code: int
    stdout: bytes = b""
    stderr: bytes = b""


class EngineError(Exception):
    pass


class Engine(Protocol):
    async def create_vm(
        self,
        *,
        sandbox_id: str,
        image: str,
        vm_type: str,
        idempotency_key: str,
    ) -> str: ...

    async def stop_vm(self, vm_id: str, *, idempotency_key: str) -> None: ...

    async def execute(self, sandbox_id: str, command: tuple[str, ...]) -> ExecResult: ...
