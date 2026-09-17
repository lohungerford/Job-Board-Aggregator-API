from fastapi import Request

from app.db.session import get_db
from app.dependencies import require_jwt_user
from app.db.models import User
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, RegisterRequest, TokenResponse
from app.services import auth_service
from app.services.jobs_service import apply_rate_limit, resolve_principal
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    principal = await resolve_principal(request, db)
    await apply_rate_limit(request, response, principal)
    return await auth_service.register_user(db, payload.email, payload.password)


@router.post("/login", response_model=TokenResponse, summary="Log in with email and password")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    principal = await resolve_principal(request, db)
    await apply_rate_limit(request, response, principal)
    return await auth_service.login_user(db, payload.email, payload.password)


@router.post("/refresh", response_model=TokenResponse, summary="Rotate a refresh token")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    principal = await resolve_principal(request, db)
    if principal.tier == "anonymous":
        # No JWT yet; keep the IP identifier so callers do not share one global bucket.
        principal.tier = "authenticated"
    await apply_rate_limit(request, response, principal)
    return await auth_service.rotate_refresh(db, payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke the current refresh token")
async def logout(
    payload: LogoutRequest,
    user: User = Depends(require_jwt_user),
    db: AsyncSession = Depends(get_db),
):
    await auth_service.logout_user(db, user.id, payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
