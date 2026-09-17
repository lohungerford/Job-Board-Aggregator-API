from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Company, Job
from app.services.ingestion import ingest_company
from app.services.normalize import infer_remote_type, infer_seniority, normalize_greenhouse_job


def test_infer_seniority_and_remote():
    assert infer_seniority("Senior Software Engineer") == "senior"
    assert infer_seniority("Staff Backend Engineer") == "staff"
    assert infer_seniority("Software Engineer Intern") == "intern"
    assert infer_remote_type("Engineer", "Remote", None) == "remote"
    assert infer_remote_type("Engineer", "New York (Hybrid)", None) == "hybrid"


def test_normalize_greenhouse_job():
    raw = {
        "id": 42,
        "title": "Junior Python Engineer",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/42",
        "location": {"name": "Remote"},
        "content": "<p>Build APIs</p>",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    normalized = normalize_greenhouse_job(raw)
    assert normalized["greenhouse_job_id"] == "42"
    assert normalized["seniority"] == "junior"
    assert normalized["remote_type"] == "remote"
    assert normalized["description"] == "Build APIs"


@pytest.mark.asyncio
async def test_ingest_upserts_and_soft_deletes(db_session):
    company = Company(name="Acme", greenhouse_board_token="acme")
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)

    first_payload = [
        {
            "id": 1,
            "title": "Senior Python Engineer",
            "absolute_url": "https://example.com/1",
            "location": {"name": "Remote"},
            "content": "Python",
            "updated_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": 2,
            "title": "Product Designer",
            "absolute_url": "https://example.com/2",
            "location": {"name": "NYC"},
            "content": "Design",
            "updated_at": "2026-01-01T00:00:00Z",
        },
    ]
    client = AsyncMock()
    with patch("app.services.ingestion.fetch_board_jobs", AsyncMock(return_value=first_payload)):
        stats = await ingest_company(db_session, company, client)
    assert stats["upserted"] == 2

    second_payload = [first_payload[0]]
    with patch("app.services.ingestion.fetch_board_jobs", AsyncMock(return_value=second_payload)):
        stats = await ingest_company(db_session, company, client)
    assert stats["closed"] == 1

    from sqlalchemy import select

    jobs = list(await db_session.scalars(select(Job)))
    closed = [job for job in jobs if job.greenhouse_job_id == "2"][0]
    assert closed.closed_at is not None
    open_job = [job for job in jobs if job.greenhouse_job_id == "1"][0]
    assert open_job.closed_at is None
    assert open_job.title == "Senior Python Engineer"


class _DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_ingest_all_fetches_boards_in_parallel(db_session, monkeypatch):
    from app.services.ingestion import ingest_all

    db_session.add(Company(name="One", greenhouse_board_token="one"))
    db_session.add(Company(name="Two", greenhouse_board_token="two"))
    await db_session.commit()

    async def fake_fetch(token, _client):
        return [
            {
                "id": token,
                "title": f"Engineer at {token}",
                "absolute_url": f"https://example.com/{token}",
                "location": {"name": "Remote"},
                "content": "Python",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]

    monkeypatch.setattr("app.services.ingestion.fetch_board_jobs", fake_fetch)
    monkeypatch.setattr("app.services.ingestion.greenhouse_client", lambda: _DummyClient())
    summary = await ingest_all(db_session)
    assert summary["companies"] == 2
    assert summary["upserted"] == 2
    assert summary["errors"] == []
