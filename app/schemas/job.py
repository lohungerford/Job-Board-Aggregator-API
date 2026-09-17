from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class RemoteType(str, Enum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"
    unknown = "unknown"


class Seniority(str, Enum):
    intern = "intern"
    junior = "junior"
    mid = "mid"
    senior = "senior"
    staff = "staff"
    lead = "lead"
    principal = "principal"


class CompanySummary(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    id: UUID
    company: CompanySummary
    greenhouse_job_id: str
    title: str
    location: str | None
    remote_type: str | None
    seniority: str | None
    description: str | None
    url: str
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None

    model_config = {"from_attributes": True}


class PaginationMeta(BaseModel):
    next_cursor: str | None = None
    has_more: bool
    limit: int


class PaginatedJobsResponse(BaseModel):
    data: list[JobResponse]
    pagination: PaginationMeta


class JobFilterParams(BaseModel):
    q: str | None = Field(default=None, max_length=200, description="Full-text keyword search")
    location: str | None = Field(default=None, max_length=200)
    remote_type: RemoteType | None = None
    seniority: Seniority | None = None
    company_id: UUID | None = None
    include_closed: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=512)


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    greenhouse_board_token: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyListResponse(BaseModel):
    data: list[CompanyResponse]
