import pytest


@pytest.mark.asyncio
async def test_health_includes_request_id(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_register_login_refresh_logout(client):
    register = await client.post(
        "/v1/auth/register",
        json={"email": "logan@example.com", "password": "supersecret"},
    )
    assert register.status_code == 201
    body = register.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    refresh = body["refresh_token"]

    login = await client.post(
        "/v1/auth/login",
        json={"email": "logan@example.com", "password": "supersecret"},
    )
    assert login.status_code == 200

    rotated = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert rotated.status_code == 200
    new_refresh = rotated.json()["refresh_token"]
    assert new_refresh != refresh

    reuse = await client.post("/v1/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "unauthorized"

    access = rotated.json()["access_token"]
    logout = await client.post(
        "/v1/auth/logout",
        json={"refresh_token": new_refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert logout.status_code == 204

    after_logout = await client.post("/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_register_conflict(client):
    payload = {"email": "dup@example.com", "password": "supersecret"}
    assert (await client.post("/v1/auth/register", json=payload)).status_code == 201
    conflict = await client.post("/v1/auth/register", json=payload)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_validation_error_names_field(client):
    response = await client.post("/v1/auth/register", json={"email": "not-an-email", "password": "short"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "email" in body["error"]["details"] or "password" in body["error"]["details"]


def test_production_rejects_placeholder_secrets():
    from app.config import Settings

    settings = Settings(
        app_env="production",
        jwt_secret="change-me-to-a-long-random-secret-at-least-32-chars",
        internal_ingest_secret="change-me-internal-ingest-secret",
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        settings.require_production_secrets()
