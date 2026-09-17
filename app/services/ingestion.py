from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Company, Job
from app.services.greenhouse_client import GreenhouseError, fetch_board_jobs, greenhouse_client
from app.services.normalize import normalize_greenhouse_job

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "companies.json"


async def ensure_seed_companies(db: AsyncSession) -> None:
    existing = await db.scalar(select(Company.id).limit(1))
    if existing is not None:
        return
    if not SEED_PATH.exists():
        return
    payload = json.loads(SEED_PATH.read_text())
    for item in payload:
        db.add(
            Company(
                name=item["name"],
                greenhouse_board_token=item["greenhouse_board_token"],
                is_active=item.get("is_active", True),
            )
        )
    await db.commit()


async def ingest_all(db: AsyncSession) -> dict:
    await ensure_seed_companies(db)
    companies = list(
        await db.scalars(select(Company).where(Company.is_active.is_(True)))
    )
    summary = {
        "companies": 0,
        "fetched": 0,
        "upserted": 0,
        "closed": 0,
        "errors": [],
    }
    # Fetch boards concurrently (I/O bound). Persist sequentially — one AsyncSession
    # must not be used from multiple tasks at once.
    fetched = await _fetch_all_boards(companies)
    for company, raw_jobs, error in fetched:
        if error is not None:
            summary["errors"].append({"company": company.name, "error": error})
            continue
        stats = await ingest_company(db, company, client=None, raw_jobs=raw_jobs)
        summary["companies"] += 1
        summary["fetched"] += stats["fetched"]
        summary["upserted"] += stats["upserted"]
        summary["closed"] += stats["closed"]
    return summary


async def _fetch_all_boards(companies: list[Company]) -> list[tuple[Company, list | None, str | None]]:
    if not companies:
        return []
    concurrency = max(1, get_settings().ingest_concurrency)
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(company: Company, client) -> tuple[Company, list | None, str | None]:
        async with semaphore:
            try:
                jobs = await fetch_board_jobs(company.greenhouse_board_token, client)
                return company, jobs, None
            except GreenhouseError as exc:
                return company, None, str(exc)

    async with greenhouse_client() as client:
        return list(await asyncio.gather(*[fetch_one(company, client) for company in companies]))


async def ingest_company(db: AsyncSession, company: Company, client=None, raw_jobs: list | None = None) -> dict[str, int]:
    if raw_jobs is None:
        if client is None:
            raise GreenhouseError("ingest_company requires a Greenhouse client or pre-fetched jobs.")
        raw_jobs = await fetch_board_jobs(company.greenhouse_board_token, client)
    now = datetime.now(UTC)
    seen_ids: set[str] = set()
    upserted = 0

    for raw in raw_jobs:
        normalized = normalize_greenhouse_job(raw)
        gh_id = normalized["greenhouse_job_id"]
        if not gh_id or not normalized["url"]:
            continue
        seen_ids.add(gh_id)
        existing = await db.scalar(
            select(Job).where(
                Job.company_id == company.id,
                Job.greenhouse_job_id == gh_id,
            )
        )
        if existing:
            existing.title = normalized["title"]
            existing.location = normalized["location"]
            existing.remote_type = normalized["remote_type"]
            existing.seniority = normalized["seniority"]
            existing.description = normalized["description"]
            existing.url = normalized["url"]
            existing.posted_at = normalized["posted_at"] or existing.posted_at
            existing.last_seen_at = now
            existing.closed_at = None
        else:
            db.add(
                Job(
                    company_id=company.id,
                    greenhouse_job_id=gh_id,
                    title=normalized["title"],
                    location=normalized["location"],
                    remote_type=normalized["remote_type"],
                    seniority=normalized["seniority"],
                    description=normalized["description"],
                    url=normalized["url"],
                    posted_at=normalized["posted_at"],
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        upserted += 1

    closed = 0
    if seen_ids:
        open_jobs = await db.scalars(
            select(Job).where(Job.company_id == company.id, Job.closed_at.is_(None))
        )
        for job in open_jobs:
            if job.greenhouse_job_id not in seen_ids:
                job.closed_at = now
                closed += 1
    elif raw_jobs == []:
        result = await db.execute(
            update(Job)
            .where(Job.company_id == company.id, Job.closed_at.is_(None))
            .values(closed_at=now)
        )
        closed = result.rowcount or 0

    await db.commit()
    return {"fetched": len(raw_jobs), "upserted": upserted, "closed": closed}
