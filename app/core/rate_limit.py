import logging
from datetime import datetime, timezone
from typing import Literal

from redis.asyncio import Redis

from app.config import get_settings
from app.core.errors import RateLimitExceeded

logger = logging.getLogger(__name__)

Tier = Literal["anonymous", "authenticated", "api_key"]

# Single Redis round-trip per request (EVAL of this script) instead of
# separate INCR/GET/EXPIRE calls. Upstash's free tier bills per command,
# so collapsing the sliding-window math into one Lua script is deliberate.
SLIDING_WINDOW_LUA = """
local current_key = KEYS[1]
local previous_key = KEYS[2]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local elapsed = now % window
local weight = (window - elapsed) / window

local current = redis.call('INCR', current_key)
if current == 1 then
  redis.call('EXPIRE', current_key, window * 2)
end

local previous = tonumber(redis.call('GET', previous_key) or '0')
local count = current + previous * weight
local remaining = math.max(0, math.floor(limit - count))
local reset = math.max(1, math.ceil(window - elapsed))
local allowed = 0
if count <= limit then
  allowed = 1
end
return {allowed, remaining, reset, math.floor(count)}
"""

_redis: Redis | None = None
_script_sha: str | None = None


async def init_redis(url: str | None) -> Redis | None:
    global _redis, _script_sha
    if not url:
        logger.warning("REDIS_URL is empty; rate limiting is disabled for this process.")
        _redis = None
        return None
    _redis = Redis.from_url(url, decode_responses=True)
    try:
        _script_sha = await _redis.script_load(SLIDING_WINDOW_LUA)
    except Exception:
        logger.exception("Failed to load rate-limit Lua script; will send EVAL by body.")
        _script_sha = None
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> Redis | None:
    return _redis


async def check_rate_limit(tier: Tier, identifier: str) -> dict[str, int]:
    settings = get_settings()
    limits = {
        "anonymous": settings.rate_limit_anonymous,
        "authenticated": settings.rate_limit_authenticated,
        "api_key": settings.rate_limit_api_key,
    }
    limit = limits[tier]
    window = settings.rate_limit_window_seconds
    client = get_redis()
    if client is None:
        return {"limit": limit, "remaining": limit, "reset": window}

    now = int(datetime.now(timezone.utc).timestamp())
    window_start = now - (now % window)
    prev_start = window_start - window
    current_key = f"rl:{tier}:{identifier}:{window_start}"
    previous_key = f"rl:{tier}:{identifier}:{prev_start}"

    try:
        if _script_sha:
            result = await client.evalsha(_script_sha, 2, current_key, previous_key, limit, window, now)
        else:
            result = await client.eval(SLIDING_WINDOW_LUA, 2, current_key, previous_key, limit, window, now)
    except Exception:
        logger.exception("Rate limit Redis call failed")
        if settings.is_production:
            from app.core.errors import AppError
            from fastapi import status

            raise AppError(
                "service_unavailable",
                "Rate limiter unavailable. Try again shortly.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return {"limit": limit, "remaining": limit, "reset": window}

    allowed, remaining, reset, _count = (int(result[0]), int(result[1]), int(result[2]), int(result[3]))
    if not allowed:
        raise RateLimitExceeded(retry_after=reset, limit=limit, window_seconds=window)
    return {"limit": limit, "remaining": remaining, "reset": reset}
