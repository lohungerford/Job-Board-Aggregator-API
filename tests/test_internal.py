import pytest


@pytest.mark.asyncio
async def test_ingest_requires_secret(client):
    missing = await client.post("/internal/ingest")
    assert missing.status_code == 401
    bad = await client.post("/internal/ingest", headers={"X-Internal-Secret": "wrong"})
    assert bad.status_code == 401
