from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db
from app.dependencies import require_jwt_user
from app.schemas.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListItem,
    ApiKeyListResponse,
)
from app.services import api_key_service

router = APIRouter(prefix="/v1/api-keys", tags=["API Keys"])


@router.get("", response_model=ApiKeyListResponse, summary="List API keys (metadata only)")
async def list_keys(
    user: User = Depends(require_jwt_user),
    db: AsyncSession = Depends(get_db),
):
    keys = await api_key_service.list_api_keys(db, user.id)
    return ApiKeyListResponse(data=[ApiKeyListItem.model_validate(k) for k in keys])


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key (raw key returned once)",
)
async def create_key(
    payload: ApiKeyCreateRequest,
    user: User = Depends(require_jwt_user),
    db: AsyncSession = Depends(get_db),
):
    record, raw = await api_key_service.create_api_key(db, user.id, payload.name)
    return ApiKeyCreateResponse(id=record.id, name=record.name, key=raw, created_at=record.created_at)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an API key")
async def delete_key(
    key_id: UUID,
    user: User = Depends(require_jwt_user),
    db: AsyncSession = Depends(get_db),
):
    await api_key_service.revoke_api_key(db, user.id, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
