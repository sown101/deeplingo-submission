
from fastapi import Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.modules.identity.application.ports import TokenVerifier
from app.modules.identity.domain.errors import AuthenticationError, AuthenticationUnavailable
from app.modules.identity.domain.principal import CurrentUser


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: TokenVerifier = Depends(get_jwt_verifier),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials.strip()
    if token.count(".") != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        # Verification may call the auth server; keep it off the event loop.
        return await run_in_threadpool(verifier.verify, token)
    except AuthenticationUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Authentication is temporarily unavailable") from None
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_authenticated_user(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    return current_user


def require_self_scoped_user(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    # Retired compatibility input: reject even matching/empty/repeated values.
    # Identity still comes exclusively from the verified CurrentUser.
    if "user_id" in request.query_params:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="user_id is not accepted; identity comes from authentication",
        )
    return current_user
