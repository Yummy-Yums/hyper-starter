from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.base import Engine, EngineError
from app.repositories.sandboxes import SandboxRepository


async def reconcile_once(
    session: AsyncSession,
    engine: Engine,
    *,
    limit: int = 100,
) -> int:
    repository = SandboxRepository(session)
    sandboxes = await repository.list_queued_for_reconcile(limit)

    changed = 0
    for sandbox in sandboxes:
        if sandbox.status != "queued":
            continue

        try:
            vm_id = await engine.create_vm(
                sandbox_id=str(sandbox.id),
                image=sandbox.image,
                vm_type=sandbox.vm_type,
                idempotency_key=str(sandbox.id),
            )
            if not vm_id:
                raise EngineError("engine returned an empty vm id")
        except EngineError as exc:
            sandbox.status = "failed"
            sandbox.failure_reason = str(exc)
        else:
            sandbox.vm_id = vm_id
            sandbox.status = "running"
            sandbox.failure_reason = None

        await repository.save(sandbox)
        changed += 1

    await session.commit()
    return changed
