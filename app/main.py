from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.rate_limit import limiter
from app.api.routes.api_keys import router as api_keys_router
from app.api.routes.health import router as health_router
from app.api.routes.sandboxes import router as sandboxes_router
from app.api.routes.tenants import router as tenants_router
from app.config import get_settings
from app.errors import DomainError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Add startup/shutdown resources here (DB checks, worker lifecycle, telemetry).
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.limiter = limiter

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_error_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limited", "message": "Rate limit exceeded"}},
        )

    app.include_router(health_router)
    app.include_router(tenants_router, prefix="/api/v1")
    app.include_router(api_keys_router, prefix="/api/v1")
    app.include_router(sandboxes_router, prefix="/api/v1")
    return app


app = create_app()
