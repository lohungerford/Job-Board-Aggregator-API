import base64
import json
from datetime import datetime
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, UnauthorizedError
from app.core.rate_limit import check_rate_limit
from app.core.security import decode_access_token, looks_like_api_key
from app.db.models import Company, Job, User
from app.schemas.job import JobFilterParams, JobResponse, PaginatedJobsResponse, PaginationMeta
from app.services.api_key_service import resolve_api_key


class Principal:
    def __init__(
        self,
        *,
        user: User | None = None,
        api_key_id: UUID | None = None,
        tier: str = "anonymous",
        identifier: str,
    ) -> None:
        self.user = user
        self.api_key_id = api_key_id
        self.tier = tier
        self.identifier = identifier

    @property
    def user_id(self) -> UUID | None:
        return None if self.user is None else self.user.id


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def resolve_principal(request: Request, db: AsyncSession) -> Principal:
    api_key_header = request.headers.get("x-api-key")
    authorization = request.headers.get("authorization") or ""
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()

    raw_key = api_key_header or (bearer if looks_like_api_key(bearer) else "")
    if raw_key:
        record = await resolve_api_key(db, raw_key)
        if record is None:
            raise UnauthorizedError("Invalid or revoked API key.")
        user = await db.get(User, record.user_id)
        return Principal(
            user=user,
            api_key_id=record.id,
            tier="api_key",
            identifier=str(record.id),
        )

    if bearer:
        try:
            user_id = decode_access_token(bearer)
        except ValueError as exc:
            raise UnauthorizedError(str(exc)) from exc
        user = await db.get(User, user_id)
        if user is None:
            raise UnauthorizedError("Invalid access token.")
        return Principal(user=user, tier="authenticated", identifier=str(user.id))

    return Principal(tier="anonymous", identifier=client_ip(request))


async def apply_rate_limit(request: Request, response: Response, principal: Principal) -> Principal:
    info = await check_rate_limit(principal.tier, principal.identifier)  # type: ignore[arg-type]
    response.headers["X-RateLimit-Limit"] = str(info["limit"])
    response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
    response.headers["X-RateLimit-Reset"] = str(info["reset"])
    return principal


def encode_cursor(posted_at: datetime | None, job_id: UUID) -> str:
    payload = {
        "t": posted_at.isoformat() if posted_at else None,
        "id": str(job_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime | None, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        posted = datetime.fromisoformat(payload["t"]) if payload.get("t") else None
        return posted, UUID(payload["id"])
    except Exception as exc:
        from app.core.errors import AppError
        from fastapi import status

        raise AppError(
            "validation_error",
            "Invalid pagination cursor.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"cursor": "Could not decode cursor"},
        ) from exc


def job_to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        company={"id": job.company.id, "name": job.company.name},
        greenhouse_job_id=job.greenhouse_job_id,
        title=job.title,
        location=job.location,
        remote_type=job.remote_type,
        seniority=job.seniority,
        description=job.description,
        url=job.url,
        posted_at=job.posted_at,
        first_seen_at=job.first_seen_at,
        last_seen_at=job.last_seen_at,
        closed_at=job.closed_at,
    )


async def list_jobs(db: AsyncSession, filters: JobFilterParams) -> PaginatedJobsResponse:
    stmt = select(Job).options(selectinload(Job.company))
    if not filters.include_closed:
        stmt = stmt.where(Job.closed_at.is_(None))
    if filters.location:
        stmt = stmt.where(Job.location.ilike(f"%{filters.location}%"))
    if filters.remote_type:
        stmt = stmt.where(Job.remote_type == filters.remote_type.value)
    if filters.seniority:
        stmt = stmt.where(Job.seniority == filters.seniority.value)
    if filters.company_id:
        stmt = stmt.where(Job.company_id == filters.company_id)
    if filters.q:
        conn = await db.connection()
        if conn.dialect.name == "postgresql":
            tsvector = func.to_tsvector(
                "english",
                func.coalesce(Job.title, "") + " " + func.coalesce(Job.description, ""),
            )
            stmt = stmt.where(tsvector.op("@@")(func.plainto_tsquery("english", filters.q)))
        else:
            like = f"%{filters.q}%"
            stmt = stmt.where(or_(Job.title.ilike(like), Job.description.ilike(like)))

    stmt = stmt.order_by(Job.posted_at.desc().nulls_last(), Job.id.desc())

    if filters.cursor:
        cursor_posted, cursor_id = decode_cursor(filters.cursor)
        if cursor_posted is None:
            stmt = stmt.where(
                and_(Job.posted_at.is_(None), Job.id < cursor_id)
                | Job.posted_at.is_not(None)
            )
        else:
            stmt = stmt.where(
                or_(
                    Job.posted_at < cursor_posted,
                    and_(Job.posted_at == cursor_posted, Job.id < cursor_id),
                    Job.posted_at.is_(None),
                )
            )

    rows = list(await db.scalars(stmt.limit(filters.limit + 1)))
    has_more = len(rows) > filters.limit
    page = rows[: filters.limit]
    next_cursor = encode_cursor(page[-1].posted_at, page[-1].id) if has_more and page else None
    return PaginatedJobsResponse(
        data=[job_to_response(job) for job in page],
        pagination=PaginationMeta(next_cursor=next_cursor, has_more=has_more, limit=filters.limit),
    )


async def get_job(db: AsyncSession, job_id: UUID) -> JobResponse:
    job = await db.scalar(select(Job).options(selectinload(Job.company)).where(Job.id == job_id))
    if job is None:
        raise NotFoundError("Job not found.")
    return job_to_response(job)


async def list_companies(db: AsyncSession) -> list[Company]:
    result = await db.scalars(select(Company).where(Company.is_active.is_(True)).order_by(Company.name.asc()))
    return list(result)
