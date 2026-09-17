from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.security import generate_api_key, hash_token
from app.db.models import ApiKey


async def create_api_key(db: AsyncSession, user_id: UUID, name: str) -> tuple[ApiKey, str]:
    raw = generate_api_key()
    record = ApiKey(user_id=user_id, name=name, key_hash=hash_token(raw))
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record, raw


async def list_api_keys(db: AsyncSession, user_id: UUID) -> list[ApiKey]:
    result = await db.scalars(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
    )
    return list(result)


async def revoke_api_key(db: AsyncSession, user_id: UUID, key_id: UUID) -> None:
    record = await db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id))
    if record is None:
        raise NotFoundError("API key not found.")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        await db.commit()


async def resolve_api_key(db: AsyncSession, raw: str) -> ApiKey | None:
    record = await db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_token(raw)))
    if record is None or record.revoked_at is not None:
        return None
    record.last_used_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(record)
    return record
