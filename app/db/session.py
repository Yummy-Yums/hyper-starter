from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def _configure_sqlite(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()


def _create_engine() -> AsyncEngine:
    database_url = get_settings().database_url
    is_sqlite = database_url.startswith("sqlite")
    engine = create_async_engine(
        database_url,
        pool_pre_ping=not is_sqlite,
        connect_args={"timeout": 30} if is_sqlite else {},
    )
    if is_sqlite:
        _configure_sqlite(engine)
    return engine


engine = _create_engine()
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with SessionFactory() as session:
        yield session
