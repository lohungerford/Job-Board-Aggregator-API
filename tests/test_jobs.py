from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Company, Job


@pytest.mark.asyncio
async def test_jobs_filter_and_pagination(client, db_session):
    company = Company(name="Acme", greenhouse_board_token="acme")
    db_session.add(company)
    await db_session.flush()
    now = datetime.now(UTC)
    for i in range(3):
        db_session.add(
            Job(
                company_id=company.id,
                greenhouse_job_id=str(i),
                title=f"Senior Python Engineer {i}",
                location="Remote - USA",
                remote_type="remote",
                seniority="senior",
                description="Python FastAPI work",
                url=f"https://example.com/{i}",
                posted_at=now - timedelta(days=i),
            )
        )
    db_session.add(
        Job(
            company_id=company.id,
            greenhouse_job_id="closed",
            title="Closed role",
            location="NYC",
            remote_type="onsite",
            seniority="junior",
            description="gone",
            url="https://example.com/closed",
            posted_at=now,
            closed_at=now,
        )
    )
    await db_session.commit()

    listed = await client.get("/v1/jobs", params={"q": "Python", "remote_type": "remote", "limit": 2})
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["pagination"]["has_more"] is True
    assert len(payload["data"]) == 2
    assert all(item["remote_type"] == "remote" for item in payload["data"])

    page2 = await client.get(
        "/v1/jobs",
        params={
            "q": "Python",
            "remote_type": "remote",
            "limit": 2,
            "cursor": payload["pagination"]["next_cursor"],
        },
    )
    assert page2.status_code == 200
    assert page2.json()["pagination"]["has_more"] is False
    ids = {item["id"] for item in payload["data"]} | {item["id"] for item in page2.json()["data"]}
    assert len(ids) == 3

    companies = await client.get("/v1/companies")
    assert companies.status_code == 200
    assert companies.json()["data"][0]["name"] == "Acme"

    job_id = payload["data"][0]["id"]
    detail = await client.get(f"/v1/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["title"].startswith("Senior Python")

    missing = await client.get("/v1/jobs/00000000-0000-0000-0000-000000000099")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    invalid = await client.get("/v1/jobs", params={"remote_type": "mars", "seniority": "mythical"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_docs_openapi_and_root_redirect(client):
    docs = await client.get("/v1/docs")
    assert docs.status_code == 200
    schema = await client.get("/v1/openapi.json")
    assert schema.status_code == 200
    assert "/v1/jobs" in schema.json()["paths"]
    root = await client.get("/", follow_redirects=False)
    assert root.status_code in {307, 302}
    assert root.headers["location"].endswith("/v1/docs")
