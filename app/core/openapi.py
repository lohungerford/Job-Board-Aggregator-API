GETTING_STARTED = """
## Getting started

This is a public, versioned REST API that aggregates Greenhouse job board postings
for a curated list of companies.

1. Register an account.
2. Use the returned access token (or log in later) on authenticated routes.
3. Optionally mint an API key for scripts and bots.

Anonymous `GET`s against `/v1/jobs` and `/v1/companies` are allowed at a lower rate limit.

### Register and make a first request

```bash
curl -s -X POST "$API/v1/auth/register" \\
  -H "Content-Type: application/json" \\
  -d '{"email":"you@example.com","password":"a-strong-password"}'

curl -s "$API/v1/jobs?q=python&remote_type=remote&limit=5" \\
  -H "Authorization: Bearer ACCESS_TOKEN"
```
"""

AUTH_GUIDE = """
## Authentication

Two independent credential systems exist:

| Mechanism | Audience | Lifetime | Header |
|---|---|---|---|
| JWT access + refresh | Human sessions (Swagger, curl while exploring) | Access ~15 minutes; refresh 7 days | `Authorization: Bearer <access_token>` |
| API key | Scripts, CLIs, bots | Until revoked | `X-API-Key: jb_...` |

### JWT flow

- `POST /v1/auth/register` and `POST /v1/auth/login` return `{ access_token, refresh_token, token_type, expires_in }`.
- Access tokens are short-lived JWTs (HS256).
- Refresh tokens are random, stored **hashed** in Postgres, and **rotated on every use**. The previous refresh token is revoked immediately.
- Reusing a revoked refresh token is treated as theft: every session for that user is revoked.
- `POST /v1/auth/logout` requires a valid access token and the current refresh token; it revokes that refresh token.

```bash
curl -s -X POST "$API/v1/auth/refresh" \\
  -H "Content-Type: application/json" \\
  -d '{"refresh_token":"REFRESH"}'

curl -s -X POST "$API/v1/auth/logout" \\
  -H "Authorization: Bearer ACCESS" \\
  -H "Content-Type: application/json" \\
  -d '{"refresh_token":"REFRESH"}'
```

### API keys

Mint keys at `POST /v1/api-keys` (JWT required). The raw key is returned **once**. Store it; the server only keeps a SHA-256 hash. List and revoke via `GET /v1/api-keys` and `DELETE /v1/api-keys/{id}`.
"""

RATE_LIMIT_GUIDE = """
## Rate limits

Sliding-window counters in Redis, one round-trip per request (Lua `EVAL`) so the
implementation stays within Upstash's per-command free-tier quota.

| Tier | Identifier | Limit | Window |
|---|---|---|---|
| Anonymous | Client IP | 30 | 1 minute |
| Authenticated (JWT) | User ID | 120 | 1 minute |
| API key | API key ID | 300 | 1 minute |

Successful and limited responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
and `X-RateLimit-Reset`. A breach is `429` with `Retry-After` and:

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded. Try again in 42 seconds.",
    "details": { "limit": 30, "window_seconds": 60 }
  }
}
```
"""

FILTER_GUIDE = """
## Filtering and pagination

`GET /v1/jobs` accepts:

- `q` — full-text search over title and description
- `location` — case-insensitive substring match
- `remote_type` — `remote` | `hybrid` | `onsite` | `unknown`
- `seniority` — `intern` | `junior` | `mid` | `senior` | `staff` | `lead` | `principal`
- `company_id` — UUID of a tracked company
- `include_closed` — include soft-deleted (closed) postings
- `limit` — 1–100, default 20
- `cursor` — opaque cursor from the previous page

Response shape:

```json
{
  "data": [ { "id": "...", "title": "...", "company": { "id": "...", "name": "..." } } ],
  "pagination": { "next_cursor": "…", "has_more": true, "limit": 20 }
}
```

Closed postings are omitted unless `include_closed=true`. Fetching `GET /v1/jobs/{id}`
returns historical (closed) jobs as well.
"""

ERROR_GUIDE = """
## Error format

Every error uses the same envelope so clients can handle failures generically:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed. See details for the offending fields.",
    "details": { "email": "value is not a valid email address" }
  }
}
```

`X-Request-ID` is set on every response for traceability.

**Free-tier notes:** Render and Neon may cold-start after idle time (first request can take several seconds). That is expected on the free tier, not an API defect.
"""


def openapi_description() -> str:
    return "\n".join(
        [
            GETTING_STARTED,
            AUTH_GUIDE,
            RATE_LIMIT_GUIDE,
            FILTER_GUIDE,
            ERROR_GUIDE,
        ]
    )
