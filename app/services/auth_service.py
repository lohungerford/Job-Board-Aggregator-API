from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.models import RefreshToken, User
from app.schemas.auth import TokenResponse


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _token_response(user: User, refresh_raw: str) -> TokenResponse:
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=refresh_raw,
        token_type="bearer",
        expires_in=settings.jwt_access_ttl_minutes * 60,
        user_id=user.id,
        email=user.email,
    )


async def _issue_refresh(db: AsyncSession, user_id: UUID) -> str:
    settings = get_settings()
    raw = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=_now() + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    return raw


async def register_user(db: AsyncSession, email: str, password: str) -> TokenResponse:
    normalized = email.lower().strip()
    existing = await db.scalar(select(User).where(User.email == normalized))
    if existing:
        raise ConflictError("An account with this email already exists.", {"email": normalized})
    user = User(email=normalized, hashed_password=hash_password(password))
    db.add(user)
    await db.flush()
    refresh_raw = await _issue_refresh(db, user.id)
    await db.commit()
    await db.refresh(user)
    return _token_response(user, refresh_raw)


async def login_user(db: AsyncSession, email: str, password: str) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user or not verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password.")
    refresh_raw = await _issue_refresh(db, user.id)
    await db.commit()
    return _token_response(user, refresh_raw)


async def rotate_refresh(db: AsyncSession, refresh_raw: str) -> TokenResponse:
    token_hash = hash_token(refresh_raw)
    row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        raise UnauthorizedError("Invalid refresh token.")
    if row.revoked_at is not None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await db.commit()
        raise UnauthorizedError("Refresh token reuse detected. All sessions have been revoked.")
    if _aware(row.expires_at) < _now():
        row.revoked_at = _now()
        await db.commit()
        raise UnauthorizedError("Refresh token expired.")

    row.revoked_at = _now()
    user = await db.get(User, row.user_id)
    if user is None:
        raise UnauthorizedError("Invalid refresh token.")
    new_raw = await _issue_refresh(db, user.id)
    await db.commit()
    return _token_response(user, new_raw)


async def logout_user(db: AsyncSession, user_id: UUID, refresh_raw: str) -> None:
    token_hash = hash_token(refresh_raw)
    row = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == user_id,
        )
    )
    if row and row.revoked_at is None:
        row.revoked_at = _now()
        await db.commit()
