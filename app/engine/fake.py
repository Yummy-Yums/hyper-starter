from app.engine.base import ExecResult, VmInfo


class FakeEngine:
    """In-memory engine test double."""

    def __init__(self) -> None:
        self.created: dict[str, tuple[str, str]] = {}
        self.stopped: list[str] = []
        self._vms_by_key: dict[str, str] = {}
        self.nodes: dict[str, str] = {}

    async def create_vm(
        self,
        *,
        sandbox_id: str,
        image: str,
        vm_type: str,
        idempotency_key: str,
    ) -> str:
        existing = self._vms_by_key.get(idempotency_key)
        if existing is not None:
            return existing

        vm_id = f"fake-{sandbox_id}"
        self._vms_by_key[idempotency_key] = vm_id
        self.created[vm_id] = (image, vm_type)
        self.nodes.setdefault(vm_id, "fake-node")
        return vm_id

    async def stop_vm(self, vm_id: str, *, idempotency_key: str) -> None:
        if vm_id not in self.stopped:
            self.stopped.append(vm_id)

    async def execute(self, sandbox_id: str, command: tuple[str, ...]) -> ExecResult:
        return ExecResult(exit_code=0, stdout=f"fake execution for {sandbox_id}".encode())

    async def list_vms(self) -> list[VmInfo]:
        running = [vm for vm in self.created if vm not in self.stopped]
        return [VmInfo(vm_id=vm, node=self.nodes.get(vm, "fake-node")) for vm in sorted(running)]
