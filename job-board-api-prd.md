# Product Requirements Document: Job Board Aggregator API

## 1. Executive Summary and Problem Statement

Entry-level and early-career job seekers spend a disproportionate amount of time searching across scattered, inconsistent job boards, many of which surface stale postings, duplicate listings, or provide no reliable way to filter for the details that matter (remote status, seniority, keyword). At the same time, this is a well-understood, well-scoped problem to build against, which makes it an ideal vehicle for demonstrating production-grade backend engineering skill.

This project is a public REST API — not an app with a backend, but an API-first product — that ingests job postings from Greenhouse's public job board API for a curated, expandable list of companies, normalizes and deduplicates them, and exposes them through a well-documented, authenticated, rate-limited API. The primary goal is a portfolio piece that demonstrates the daily skills of a senior backend engineer: authentication and authorization, API key issuance and management, rate limiting, versioning, pagination, structured error handling, and technical documentation as a first-class deliverable. The secondary goal is that the API is genuinely useful — to the author's own job search and to other developers who want programmatic access to curated job data.

The project must be buildable and operable at effectively zero ongoing cost, using free-tier infrastructure throughout, with any point where a "best practice" choice would introduce cost explicitly flagged and given a free-tier-compatible alternative.

## 2. Goals and Non-Goals for v1

**Goals:**
- Ship a versioned, authenticated, rate-limited public REST API for querying aggregated Greenhouse job postings.
- Demonstrate JWT authentication with refresh token rotation, independent API key management, Redis-backed rate limiting, request validation, consistent error responses, and first-class OpenAPI documentation.
- Keep the entire system runnable on free-tier infrastructure indefinitely at low traffic.
- Produce a deliverable specific enough to scaffold directly with an AI coding assistant.

**Non-goals for v1 (explicitly out of scope):**
- A frontend UI or dashboard of any kind. This is a stretch/future phase, not a v1 deliverable.
- Multi-region deployment or high-availability architecture.
- Any paid infrastructure or services, including paid tiers of the free services recommended below.
- Ingestion sources other than Greenhouse's public API (no LinkedIn scraping, no Lever, no Indeed).
- Saved searches, alerts, and webhook notifications are stretch goals, not MVP.

## 3. Target Users

- **Individual developers and job seekers** who query the API directly (via curl, Postman, or a browser hitting the Swagger UI) to search postings without dealing with the noise of company career pages.
- **Developers building small tools on top of the API**: a personal CLI script, a Slack/Discord bot that posts new matching jobs, a personal dashboard or spreadsheet sync, a resume-tailoring tool that pulls live job descriptions.
- **Technical reviewers** — hiring managers and engineers evaluating this as a portfolio project — who will read the docs, hit the live endpoints, and inspect the code and architecture decisions.

## 4. Core Features

### MVP (v1)
1. **Job ingestion from Greenhouse** for a curated, expandable list of companies, run on a schedule (see Section 5 for the scheduling mechanism).
2. **Deduplication and normalization**: postings are keyed by a stable identifier (Greenhouse job ID + company), reposts are recognized rather than duplicated, and postings no longer present in a company's feed are marked closed rather than deleted outright (soft-delete, so historical data and any saved-search stretch feature stay meaningful).
3. **Search and filtering**: keyword full-text search plus filters for location, seniority level (parsed/inferred from title where possible), remote/hybrid/onsite, and company — all with consistent, cursor- or offset-based pagination.
4. **JWT authentication** with access + refresh tokens, refresh token rotation, and revocation on logout.
5. **API key management**: authenticated users can generate, list, and revoke their own API keys for programmatic (non-browser) access, independent of their JWT session.
6. **Redis-backed rate limiting** with distinct limits for anonymous, authenticated, and API-key traffic.
7. **Consistent error response format** across every endpoint (see Section 8/10).
8. **Request validation** on all inputs (query params, bodies) via Pydantic models, with actionable error messages naming the offending field.
9. **URL-based API versioning** (`/v1/...`) from day one.
10. **Published OpenAPI documentation** via FastAPI's built-in Swagger UI and/or Redoc, treated as a deliverable with hand-written usage guides layered on top of the auto-generated schema (Section 9).

### Stretch Goals (post-v1)
- Saved searches and email/webhook alerts for new matching postings.
- A minimal read-only dashboard (separate frontend project, out of scope for this PRD).
- Webhook subscriptions so external tools get pushed notifications instead of polling.
- Additional ingestion sources (Lever, Ashby) behind the same normalized schema.

## 5. Technical Architecture

### Backend: FastAPI (Python)
FastAPI is chosen for native `async`/`await` support (important for I/O-bound work like calling the Greenhouse API and Postgres queries under concurrent load) and for its built-in generation of an OpenAPI schema and Swagger UI directly from Pydantic models and route type hints — this turns "publish API documentation" from a separate task into a natural byproduct of well-typed code, while still leaving room for the hand-written documentation layer required in Section 9.

### Database: PostgreSQL
Recommended host: **Neon** (serverless Postgres, generous free tier, scales to zero when idle which pairs well with a low-traffic portfolio project) or **Supabase** (free tier includes Postgres + built-in auth helpers, though this PRD specifies rolling your own JWT auth for the resume value of having built it). Either is free-tier-friendly.

*Free-tier limits to design around:* Neon's free tier caps storage (roughly 0.5GB) and has some compute/autosuspend behavior after inactivity, meaning the first query after idle time will be slower (cold start) — acceptable for a portfolio project, and worth mentioning in the docs so evaluators aren't surprised by an occasional slow first request. Keep the schema lean (Section 6) to stay well within storage limits even with months of accumulated job postings.

### Caching / Rate Limiting: Redis
Recommended host: **Upstash** (serverless Redis, pay-per-request free tier with a fixed daily command allotment, no persistent connection required which suits serverless/low-traffic deployments).

*Free-tier limits to design around:* Upstash's free tier caps daily commands and max database size. Rate-limiting logic should use minimal Redis round-trips per request (e.g., a single Lua script or a single `INCR` + `EXPIRE` pair) rather than one command per rate-limit check, to conserve the daily quota as traffic grows. Flag this explicitly in code comments so a future maintainer (or interviewer) sees the cost-awareness was deliberate.

### Authentication
- **JWT**: short-lived access tokens (e.g., 15 minutes) and longer-lived refresh tokens (e.g., 7–14 days), signed with a secret (HS256) or asymmetric key (RS256 — slightly more resume-impressive, still free). Refresh tokens are rotated on every use (old one invalidated, new one issued) and stored hashed in Postgres so a stolen refresh token can be revoked. Passwords hashed with `bcrypt` or `argon2` (via `passlib`).
- **API keys**: generated as a random 32+ byte token, shown to the user exactly once at creation, stored in the database as a **hash** (SHA-256 or bcrypt) rather than plaintext — verification re-hashes the incoming key and compares. This is architecturally separate from the JWT system: API keys authenticate machine/script access and never expire unless revoked, while JWTs authenticate the human session.

### Background Job Handling (Ingestion Scheduling)
Given the zero-cost constraint, avoid infrastructure that requires a dedicated always-on worker dyno (which most free tiers either don't offer or sleep aggressively). Two free-tier-compatible options, in order of recommendation:
1. **Cron-triggered endpoint**: expose an internal `/internal/ingest` endpoint protected by a secret header, and trigger it on a schedule using a free external cron service (e.g., GitHub Actions scheduled workflow calling `curl`, or cron-job.org). This avoids keeping any process alive and works even if the host sleeps between requests.
2. **In-process APScheduler**: run `APScheduler` inside the FastAPI app itself, only viable if the host provides an always-on free instance (most, like Render's free web service tier, spin down on inactivity, which would silently kill the scheduler — flag this as a real risk if chosen).

**Recommendation for this PRD: the cron-triggered endpoint via GitHub Actions**, since it's genuinely free with no sleep/wake ambiguity and is itself a small, resume-worthy detail ("scheduled ingestion via GitHub Actions cron calling a secured internal endpoint").

### Deployment
Recommended host: **Render free web service tier** (or Fly.io free allowance as an alternative).

*Honest limitations:* Render's free tier spins the service down after a period of inactivity, so the first request after idle time incurs a cold start of several seconds to ~a minute. Design around this by: (a) documenting the behavior clearly in the API docs so evaluators aren't confused by a slow first request, (b) optionally using a scheduled low-frequency health-check ping (e.g., every 10 minutes from the same GitHub Actions cron used for ingestion) to keep it warmer during expected review hours, while being mindful this doesn't count as "real" uptime and shouldn't be oversold. There is also a monthly free-tier compute-hours cap — low-traffic personal/portfolio use should comfortably fit within it.

### Suggested Project Structure
```
job-board-api/
├── app/
│   ├── main.py                 # FastAPI app instantiation, router includes, middleware
│   ├── config.py                # Settings via pydantic-settings, reads env vars
│   ├── dependencies.py          # Shared FastAPI dependencies (get_db, get_current_user, get_api_key_user)
│   ├── db/
│   │   ├── base.py               # SQLAlchemy declarative base, session factory
│   │   └── models.py             # ORM models: User, RefreshToken, ApiKey, Company, Job, SavedSearch
│   ├── schemas/
│   │   ├── auth.py               # Pydantic: RegisterRequest, LoginRequest, TokenResponse
│   │   ├── job.py                # Pydantic: JobResponse, JobFilterParams, PaginatedJobsResponse
│   │   └── api_key.py            # Pydantic: ApiKeyCreateResponse, ApiKeyListItem
│   ├── routers/
│   │   ├── v1/
│   │   │   ├── auth.py            # /v1/auth/register, /login, /refresh, /logout
│   │   │   ├── jobs.py            # /v1/jobs, /v1/jobs/{id}
│   │   │   ├── api_keys.py        # /v1/api-keys (GET/POST), /v1/api-keys/{id} (DELETE)
│   │   │   └── companies.py       # /v1/companies
│   │   └── internal.py           # /internal/ingest (cron-triggered, secret-protected)
│   ├── services/
│   │   ├── greenhouse_client.py   # Fetch + parse Greenhouse public job board API
│   │   ├── ingestion.py           # Dedup/normalize/soft-delete logic
│   │   ├── auth_service.py        # Password hashing, JWT issuance/verification, refresh rotation
│   │   └── api_key_service.py     # API key generation, hashing, verification
│   ├── core/
│   │   ├── security.py            # Shared crypto helpers (hash/verify password, hash/verify api key)
│   │   ├── rate_limit.py          # Redis-backed limiter (dependency, per-tier logic)
│   │   └── errors.py              # Custom exception classes + shared exception handlers
│   └── middleware/
│       └── request_id.py          # Adds a request ID to every response for traceability
├── alembic/                      # DB migrations
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

## 6. Data Model

```sql
-- Users
users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  hashed_password TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- Refresh tokens (hashed, one row per active session/device)
refresh_tokens (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- API keys (hashed, user can hold multiple)
api_keys (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,               -- user-provided label, e.g. "personal script"
  key_hash TEXT NOT NULL UNIQUE,
  last_used_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- Companies / sources
companies (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  greenhouse_board_token TEXT UNIQUE NOT NULL,  -- Greenhouse's identifier for the company's board
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

-- Jobs
jobs (
  id UUID PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  greenhouse_job_id TEXT NOT NULL,   -- source ID, unique per company
  title TEXT NOT NULL,
  location TEXT,
  remote_type TEXT,                  -- 'remote' | 'hybrid' | 'onsite' | 'unknown'
  seniority TEXT,                    -- parsed/inferred, nullable
  description TEXT,
  url TEXT NOT NULL,
  posted_at TIMESTAMPTZ,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ,             -- soft-delete marker, null while active
  UNIQUE (company_id, greenhouse_job_id)
)

-- Saved searches (stretch)
saved_searches (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  filters JSONB NOT NULL,            -- serialized filter params
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

Indexes worth adding from day one: `jobs(company_id, closed_at)`, a full-text/GIN index on `jobs(title, description)` for keyword search, and `jobs(location)` / `jobs(remote_type)` for filtering.

## 7. API Design

| Method | Path | Purpose | Auth Required | Rate Limit Tier |
|---|---|---|---|---|
| POST | `/v1/auth/register` | Create a new user account | None | Anonymous |
| POST | `/v1/auth/login` | Exchange credentials for access + refresh token | None | Anonymous |
| POST | `/v1/auth/refresh` | Rotate refresh token, issue new access token | Refresh token | Authenticated |
| POST | `/v1/auth/logout` | Revoke current refresh token | JWT | Authenticated |
| GET | `/v1/jobs` | List/search/filter jobs, paginated | Optional | Anonymous / Authenticated / API key (varies) |
| GET | `/v1/jobs/{id}` | Get a single job posting | Optional | Anonymous / Authenticated / API key |
| GET | `/v1/companies` | List curated companies being tracked | Optional | Anonymous / Authenticated / API key |
| GET | `/v1/api-keys` | List the current user's API keys (metadata only, never the raw key) | JWT | Authenticated |
| POST | `/v1/api-keys` | Generate a new API key (raw key returned once) | JWT | Authenticated |
| DELETE | `/v1/api-keys/{id}` | Revoke an API key | JWT | Authenticated |
| POST | `/internal/ingest` | Trigger a Greenhouse ingestion run | Internal secret header | N/A (not public) |

`GET /v1/jobs` and `GET /v1/jobs/{id}` are intentionally open to anonymous callers at a low rate limit, since a job board's core value is discoverability — but authenticated and API-key callers get materially higher limits, which is the whole point of having tiers.

## 8. Rate Limiting Spec

**Algorithm: sliding window counter**, implemented in Redis with a single `INCR` + `EXPIRE` (or a Lua script for atomicity) keyed by `{tier}:{identifier}:{window_start}`. A sliding window is preferred over a naive token bucket here because it's simpler to reason about and implement correctly with minimal Redis commands (important given Upstash's per-command free-tier quota), while still avoiding the burst-at-window-boundary problem of a fixed window counter.

**Limits per tier (initial values, tunable):**

| Tier | Identifier | Limit | Window |
|---|---|---|---|
| Anonymous | Client IP | 30 requests | 1 minute |
| Authenticated (JWT) | User ID | 120 requests | 1 minute |
| API key | API key ID | 300 requests | 1 minute |

**Behavior on limit breach:**
- HTTP status `429 Too Many Requests`
- Headers: `Retry-After: <seconds>`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Body (matches the standard error format in Section 10):
```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded. Try again in 42 seconds.",
    "details": { "limit": 30, "window_seconds": 60 }
  }
}
```

## 9. API Documentation Plan

FastAPI's auto-generated OpenAPI schema (served at `/v1/docs` via Swagger UI, and optionally `/v1/redoc`) covers the mechanical contract — endpoints, request/response shapes, status codes. That alone is not sufficient as a portfolio deliverable; the documentation should also include, as hand-written Markdown injected into the OpenAPI description fields (FastAPI supports rich Markdown in `description=` and tags):

- **Getting started guide**: how to register, obtain a token, and make a first authenticated request, with copy-pasteable `curl` examples.
- **Authentication walkthrough**: the difference between JWT (session) auth and API key (programmatic) auth, when to use each, and the full refresh-token rotation flow with example requests/responses.
- **Rate limit explanation**: the tier table, how to read the rate-limit response headers, and what a `429` response looks like.
- **Filtering and pagination guide**: example queries against `/v1/jobs` showing combined filters and how to read pagination metadata in the response.
- **Error format reference**: the canonical error shape (Section 10) so consumers can write generic error-handling code against it.

This documentation should be treated as a deliverable reviewed and polished in its own milestone (Section 11), not generated once and left as-is.

## 10. Security Considerations

- **Password storage**: hashed with `bcrypt` (or `argon2` via `passlib`), never logged or returned in any response.
- **JWT handling**: short-lived access tokens; refresh tokens stored server-side as a hash (not the raw token), rotated on every refresh, with the old token marked revoked immediately so a leaked-and-reused refresh token is detectable and containable. Tokens transmitted only over HTTPS.
- **API key handling**: generated with a cryptographically secure random source, shown once, stored as a hash. Revocation sets `revoked_at` and is checked on every request — no caching of "is this key valid" beyond the rate-limit window's TTL, to keep revocation effectively immediate.
- **Input validation/sanitization**: all request bodies and query params validated through Pydantic models with explicit types and constraints (e.g., max string lengths, enum values for `remote_type`); SQLAlchemy's parameterized queries prevent SQL injection by construction as long as raw SQL string interpolation is avoided everywhere.
- **CORS policy**: since this is a public API meant to be consumed by arbitrary third-party scripts and tools (not just a single first-party frontend), CORS should allow all origins (`*`) for the public `GET` endpoints, while auth-sensitive endpoints still require a valid bearer token or API key regardless of origin — CORS is not a substitute for auth here, just a convenience for browser-based callers.

## 11. Milestones (Solo, Part-Time Build Plan)

- **Phase 1 — Data model + Greenhouse ingestion**: schema + migrations, Greenhouse client, ingestion/dedup/normalization logic, manually triggered ingestion working end-to-end for a handful of companies.
- **Phase 2 — Search/pagination endpoints**: `/v1/jobs`, `/v1/jobs/{id}`, `/v1/companies` with filtering, full-text search, and pagination, no auth yet.
- **Phase 3 — JWT auth + refresh rotation**: register/login/refresh/logout, password hashing, refresh token storage and rotation.
- **Phase 4 — API key management + Redis rate limiting**: API key generation/list/revoke, Redis-backed sliding-window limiter wired into all endpoints per the tier table.
- **Phase 5 — Documentation + deployment + polish**: hand-written docs layered onto Swagger/Redoc, deploy to Render, wire up the GitHub Actions cron for ingestion (and optional keep-warm ping), README polish, error-format consistency pass across every endpoint.

Each phase is independently demoable, which matters for a part-time solo build — there's a working, showable artifact after every phase rather than only at the very end.

## 12. Resume/Portfolio Framing

This project demonstrates, concretely and independently verifiably (via the live docs link and deployed API):

- **Authentication engineering**: JWT access/refresh flow with server-side refresh token rotation and revocation — a pattern directly transferable to production auth systems.
- **API key infrastructure**: designing a secondary, independently-managed credential system (generation, hashed storage, revocation) separate from user session auth — a common real-world requirement for any API product.
- **Rate limiting at the infrastructure level**: a Redis-backed sliding-window limiter with distinct tiers, correct HTTP semantics (`429`, `Retry-After`), and quota-conscious implementation choices under a real free-tier constraint.
- **API versioning and lifecycle discipline**: URL-based versioning planned from v1, not retrofitted.
- **Request validation and error-response standards**: consistent, predictable error shapes across an entire API surface — a detail that separates "a working API" from "an API other engineers would enjoy integrating with."
- **Technical documentation as a deliverable**: hand-authored guides layered on generated OpenAPI docs, treating documentation as a first-class artifact rather than an afterthought.
- **Cost-aware infrastructure decisions**: every technical choice made under a real zero-budget constraint, with explicit trade-off reasoning — a skill directly relevant to startup/early-stage engineering roles.

**Resume bullet starting points** (tailor wording to the actual finished project):
- "Designed and built a versioned, rate-limited public REST API in FastAPI aggregating job postings from Greenhouse's public API, implementing JWT auth with refresh token rotation and an independent API key system for programmatic access."
- "Implemented a Redis-backed sliding-window rate limiter with per-tier limits (anonymous/authenticated/API key), reducing to a single Redis round-trip per request to operate within free-tier quota constraints."
- "Authored first-class API documentation (Swagger/Redoc) including authentication walkthroughs and rate-limit guides, alongside a fully automated ingestion pipeline triggered via scheduled GitHub Actions."

**Presenting it on a resume**: link the live Swagger/Redoc docs URL directly (e.g., `api.yourproject.com/v1/docs`) rather than just a GitHub link — a hiring manager clicking through to a live, interactive API surface is more persuasive than a README. Pair it with the GitHub repo link for code review, and consider a one-line README badge or note describing uptime caveats (cold starts on the free tier) so reviewers aren't confused if the first request is slow.
