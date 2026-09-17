from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_principal
from app.schemas.job import CompanyListResponse, CompanyResponse
from app.services import jobs_service
from app.services.jobs_service import Principal

router = APIRouter(prefix="/v1/companies", tags=["Companies"])


@router.get("", response_model=CompanyListResponse, summary="List curated companies being tracked")
async def list_companies(
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(get_principal),
):
    companies = await jobs_service.list_companies(db)
    return CompanyListResponse(data=[CompanyResponse.model_validate(c) for c in companies])
