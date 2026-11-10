from fastapi import Request
from slowapi import Limiter

from app.config import get_settings


def tenant_key(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is not None:
        return str(tenant_id)
    return request.client.host if request.client is not None else "anonymous"


def rate_limit_value() -> str:
    return f"{get_settings().rate_limit_per_minute}/minute"


limiter = Limiter(key_func=tenant_key)
