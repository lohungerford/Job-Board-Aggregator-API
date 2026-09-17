import pytest

from app.core import rate_limit
from app.core.errors import RateLimitExceeded
from app.core.rate_limit import check_rate_limit


class _CountingRedis:
    """Stand-in for Redis EVAL: fakeredis without Lua extras does not run the script."""

    def __init__(self) -> None:
        self.count = 0

    async def evalsha(self, _sha, _nkeys, _current_key, _previous_key, limit, window, _now):
        return self._tick(int(limit), int(window))

    async def eval(self, _script, _nkeys, _current_key, _previous_key, limit, window, _now):
        return self._tick(int(limit), int(window))

    def _tick(self, limit: int, window: int) -> list[int]:
        self.count += 1
        allowed = 1 if self.count <= limit else 0
        remaining = max(0, limit - self.count)
        return [allowed, remaining, window, self.count]


@pytest.mark.asyncio
async def test_sliding_window_rate_limit(monkeypatch):
    rate_limit._redis = _CountingRedis()
    rate_limit._script_sha = "unused"

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_anonymous", 3)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)

    for _ in range(3):
        info = await check_rate_limit("anonymous", "1.2.3.4")
        assert info["remaining"] >= 0

    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_rate_limit("anonymous", "1.2.3.4")
    assert exc_info.value.retry_after >= 1

    rate_limit._redis = None
    rate_limit._script_sha = None


@pytest.mark.asyncio
async def test_rate_limit_headers_on_429(client, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RateLimitExceeded(retry_after=42, limit=30, window_seconds=60)

    monkeypatch.setattr("app.services.jobs_service.check_rate_limit", boom)
    response = await client.get("/v1/jobs")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"
    assert response.headers["x-ratelimit-limit"] == "30"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert response.headers["x-ratelimit-reset"] == "42"
    body = response.json()
    assert body["error"]["code"] == "rate_limit_exceeded"
    assert body["error"]["details"]["limit"] == 30
