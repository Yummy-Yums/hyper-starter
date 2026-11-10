from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.deps import SessionDep
from app.services.api_keys import ApiKeyService

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthContext:
    tenant_id: UUID
    api_key_id: UUID


async def get_auth_context(
    request: Request,
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    api_key = await ApiKeyService(session).authenticate(credentials.credentials)
    if api_key is None:
        raise _unauthorized()

    request.state.tenant_id = api_key.tenant_id
    request.state.api_key_id = api_key.id
    return AuthContext(tenant_id=api_key.tenant_id, api_key_id=api_key.id)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


AuthContextDep = Annotated[AuthContext, Depends(get_auth_context)]
