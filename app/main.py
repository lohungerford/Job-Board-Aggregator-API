from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.openapi import openapi_description
from app.core.rate_limit import close_redis, init_redis
from app.middleware.request_id import RequestIdMiddleware
from app.routers.internal import router as internal_router
from app.routers.v1.api_keys import router as api_keys_router
from app.routers.v1.auth import router as auth_router
from app.routers.v1.companies import router as companies_router
from app.routers.v1.jobs import router as jobs_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.require_production_secrets()
    await init_redis(settings.redis_url or None)
    yield
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=openapi_description(),
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/v1/docs")


app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(companies_router)
app.include_router(api_keys_router)
app.include_router(internal_router)


@app.get("/health", tags=["Health"], summary="Liveness probe / keep-warm ping")
async def health():
    return {"status": "ok"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "JWT access token from /v1/auth/login or /v1/auth/register.",
    }
    schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API key minted at POST /v1/api-keys. Shown only once.",
    }
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
