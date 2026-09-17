# Job Board Aggregator API

Public REST API that ingests Greenhouse job-board postings for a curated company list, normalizes and deduplicates them, and exposes search through a versioned, authenticated, rate-limited surface.

Interactive docs: `/v1/docs` (Swagger) and `/v1/redoc`.

## Why this exists

Entry-level search is noisy: stale posts, duplicates, weak filters. This API is an API-first portfolio product that is also useful for personal job search scripts. It demonstrates JWT refresh-token rotation, hashed API keys, Redis sliding-window rate limits, cursor pagination, and consistent errors — on free-tier infrastructure.

## Features (v1)

- Greenhouse ingestion with upsert + soft-delete (`closed_at`)
- Keyword search and filters: location, remote type, seniority, company
- Cursor pagination
- JWT access + refresh tokens with rotation and reuse detection
- API keys (shown once, stored as SHA-256)
- Redis rate limits: anonymous 30/min, JWT 120/min, API key 300/min
- Canonical error envelope and `X-Request-ID`
- OpenAPI docs with getting-started, auth, rate-limit, filter, and error guides

## Quick start (local)

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Postgres + Redis
docker compose up db redis -d
alembic upgrade head
uvicorn app.main:app --reload
```

Open http://localhost:8000/v1/docs.

Register, then trigger a first ingest (seeds default companies if the table is empty):

```bash
curl -X POST http://localhost:8000/internal/ingest \
  -H "X-Internal-Secret: $INTERNAL_INGEST_SECRET"
```

## Authentication

**JWT (human session)** — `POST /v1/auth/register` or `/v1/auth/login` returns `access_token` + `refresh_token`. Send `Authorization: Bearer <access_token>`. Access tokens last 15 minutes. `POST /v1/auth/refresh` rotates the refresh token (old one is revoked). Reusing a revoked refresh token revokes every session for that user.

**API keys (scripts)** — `POST /v1/api-keys` with a JWT. The raw `jb_...` key is returned once. Send `X-API-Key: jb_...`. Keys never expire until `DELETE /v1/api-keys/{id}`.

Job and company GETs work anonymously at the lowest rate limit.

## Rate limits

| Tier | Identifier | Limit / minute |
|---|---|---|
| Anonymous | IP | 30 |
| JWT | User ID | 120 |
| API key | Key ID | 300 |

Implemented as a sliding-window counter in Redis with a **single Lua `EVAL` per request** so Upstash's per-command free-tier quota is not burned on multiple round-trips. Responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`. Breaches are `429` with `Retry-After`.

If `REDIS_URL` is empty, rate limiting is skipped (local convenience only).

## Errors

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed. See details for the offending fields.",
    "details": { "email": "value is not a valid email address" }
  }
}
```

## Ingestion

`POST /internal/ingest` is protected by `X-Internal-Secret`. GitHub Actions (`.github/workflows/ingest.yml`) calls it every 6 hours and pings `/health` every 10 minutes to reduce Render free-tier cold starts. That is not guaranteed uptime. Configure repository secrets:

- `API_BASE_URL` — deployed origin, no trailing slash
- `INTERNAL_INGEST_SECRET` — same value as the service env var

Closed jobs are marked with `closed_at` rather than deleted.

## Free-tier operations

| Service | Role | Caveat |
|---|---|---|
| Render (or Fly) | API | Spins down when idle; first request after sleep can take seconds to ~a minute |
| Neon (or Supabase Postgres) | Database | Autosuspend; first query after idle is slower |
| Upstash Redis | Rate limits | Daily command quota — hence one Redis round-trip per request |

Document these to reviewers so a slow first request is not mistaken for a bug.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Pull requests run the same suite via `.github/workflows/ci.yml`.

## Project layout

Matches the PRD: `app/main.py`, `app/routers/v1/*`, `app/services/*`, `app/core/*`, Alembic migrations, and tests.

## Deploy (Render)

1. Create a Neon Postgres database and an Upstash Redis database.
2. Create a Render web service from this repo (Docker), or use the `render.yaml` blueprint.
3. Set `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `INTERNAL_INGEST_SECRET`, `APP_ENV=production`.
   Production boot refuses placeholder `change-me` secrets.
4. Run `alembic upgrade head` (the Docker CMD already does this on boot).
5. Add the GitHub Actions secrets and enable the ingest workflow.

`DATABASE_URL` values that start with `postgres://` are rewritten to `postgresql+asyncpg://` automatically.
