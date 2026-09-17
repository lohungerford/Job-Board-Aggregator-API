import pytest


async def _register(client):
    response = await client.post(
        "/v1/auth/register",
        json={"email": "keys@example.com", "password": "supersecret"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_api_key_lifecycle(client):
    tokens = await _register(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    created = await client.post("/v1/api-keys", json={"name": "personal script"}, headers=headers)
    assert created.status_code == 201
    raw = created.json()["key"]
    assert raw.startswith("jb_")
    key_id = created.json()["id"]

    listed = await client.get("/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["name"] == "personal script"
    assert "key" not in listed.json()["data"][0]

    jobs = await client.get("/v1/jobs", headers={"X-API-Key": raw})
    assert jobs.status_code == 200
    assert jobs.headers.get("x-ratelimit-limit") == "300"

    revoked = await client.delete(f"/v1/api-keys/{key_id}", headers=headers)
    assert revoked.status_code == 204

    denied = await client.get("/v1/jobs", headers={"X-API-Key": raw})
    assert denied.status_code == 401

    jwt_only = await client.post(
        "/v1/api-keys",
        json={"name": "from key"},
        headers={"X-API-Key": raw},
    )
    assert jwt_only.status_code == 401
