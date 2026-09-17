from typing import Any

import httpx

from app.config import get_settings

GREENHOUSE_JOBS_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseError(Exception):
    pass


async def fetch_board_jobs(board_token: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
    url = GREENHOUSE_JOBS_URL.format(token=board_token)
    try:
        response = await client.get(url, params={"content": "true"})
    except httpx.HTTPError as exc:
        raise GreenhouseError(f"Failed to reach Greenhouse for '{board_token}': {exc}") from exc
    if response.status_code == 404:
        raise GreenhouseError(f"Greenhouse board '{board_token}' was not found.")
    if response.status_code >= 400:
        raise GreenhouseError(
            f"Greenhouse returned {response.status_code} for '{board_token}'."
        )
    payload = response.json()
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return []
    return jobs


def greenhouse_client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=settings.greenhouse_timeout_seconds,
        headers={"User-Agent": "job-board-aggregator-api/1.0"},
    )
