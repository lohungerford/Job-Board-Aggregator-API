from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import require_internal_secret
from app.services.ingestion import ingest_all

router = APIRouter(prefix="/internal", tags=["Internal"])


@router.post(
    "/ingest",
    summary="Trigger Greenhouse ingestion (cron / GitHub Actions)",
    dependencies=[Depends(require_internal_secret())],
)
async def ingest(db: AsyncSession = Depends(get_db)):
    return await ingest_all(db)
