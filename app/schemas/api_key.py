from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["personal script"])


class ApiKeyCreateResponse(BaseModel):
    id: UUID
    name: str
    key: str
    created_at: datetime


class ApiKeyListItem(BaseModel):
    id: UUID
    name: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyListResponse(BaseModel):
    data: list[ApiKeyListItem]
