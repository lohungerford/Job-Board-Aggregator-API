from collections.abc import Callable

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.db.models import User
from app.db.session import get_db
from app.services.jobs_service import Principal, apply_rate_limit, resolve_principal


async def get_principal(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> Principal:
    principal = await resolve_principal(request, db)
    return await apply_rate_limit(request, response, principal)


async def get_optional_user(principal: Principal = Depends(get_principal)) -> Principal:
    return principal


async def get_current_user(principal: Principal = Depends(get_principal)) -> User:
    if principal.user is None or principal.tier == "anonymous":
        raise UnauthorizedError("Authentication required.")
    if principal.tier == "api_key":
        # API keys authenticate machine traffic, not session management endpoints.
        raise UnauthorizedError("This endpoint requires a JWT access token.")
    return principal.user


async def require_jwt_user(principal: Principal = Depends(get_principal)) -> User:
    if principal.tier != "authenticated" or principal.user is None:
        raise UnauthorizedError("A JWT access token is required.")
    return principal.user


def require_internal_secret(header_name: str = "x-internal-secret") -> Callable:
    from app.config import get_settings
    from app.core.security import constant_time_equals
    from fastapi import Header

    async def _dep(secret: str = Header(default="", alias=header_name)) -> None:
        expected = get_settings().internal_ingest_secret
        if not secret or not constant_time_equals(secret, expected):
            raise UnauthorizedError("Invalid internal secret.")

    return _dep
