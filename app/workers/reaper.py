from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.engine.base import Engine, EngineError
from app.repositories.sandboxes import SandboxRepository


async def run_reaper_once(
    session: AsyncSession,
    engine: Engine,
    *,
    now: datetime | None = None,
    idle_timeout_seconds: int | None = None,
    limit: int = 100,
) -> int:
    reaped_at = now or datetime.now(UTC)
    if idle_timeout_seconds is None:
        idle_timeout_seconds = get_settings().sandbox_idle_timeout_seconds
    idle_cutoff = reaped_at - timedelta(seconds=idle_timeout_seconds)

    repository = SandboxRepository(session)
    sandboxes = await repository.list_reapable(
        now=reaped_at,
        idle_cutoff=idle_cutoff,
        limit=limit,
    )

    changed = 0
    for sandbox in sandboxes:
        if sandbox.status not in ("queued", "running"):
            continue

        if sandbox.vm_id is not None:
            try:
                await engine.stop_vm(
                    sandbox.vm_id,
                    idempotency_key=str(sandbox.id),
                )
            except EngineError as exc:
                sandbox.failure_reason = f"reaper stop failed: {exc}"
                await repository.save(sandbox)
                continue

        sandbox.status = "stopped"
        sandbox.stopped_at = reaped_at
        sandbox.failure_reason = None
        await repository.save(sandbox)
        changed += 1

    await session.commit()
    return changed
