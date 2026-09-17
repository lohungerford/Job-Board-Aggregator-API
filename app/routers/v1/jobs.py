from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_principal
from app.schemas.job import (
    JobFilterParams,
    JobResponse,
    PaginatedJobsResponse,
    RemoteType,
    Seniority,
)
from app.services import jobs_service
from app.services.jobs_service import Principal

router = APIRouter(prefix="/v1/jobs", tags=["Jobs"])


@router.get(
    "",
    response_model=PaginatedJobsResponse,
    summary="Search and filter aggregated job postings",
)
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(get_principal),
    q: str | None = Query(default=None, max_length=200),
    location: str | None = Query(default=None, max_length=200),
    remote_type: RemoteType | None = Query(default=None),
    seniority: Seniority | None = Query(default=None),
    company_id: UUID | None = Query(default=None),
    include_closed: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
):
    filters = JobFilterParams(
        q=q,
        location=location,
        remote_type=remote_type,
        seniority=seniority,
        company_id=company_id,
        include_closed=include_closed,
        limit=limit,
        cursor=cursor,
    )
    return await jobs_service.list_jobs(db, filters)


@router.get("/{job_id}", response_model=JobResponse, summary="Get a single job posting")
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(get_principal),
):
    return await jobs_service.get_job(db, job_id)
