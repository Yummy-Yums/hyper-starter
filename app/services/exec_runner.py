from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    sandbox_id: str
    command: tuple[str, ...]


class ExecutionRunner:
    """Application-level boundary for execution; never execute untrusted input directly."""

    async def run(self, request: ExecutionRequest) -> dict[str, object]:
        # Connect this to the Engine protocol/adapter. This is deliberately a safe stub.
        return {"sandbox_id": request.sandbox_id, "accepted": bool(request.command)}
