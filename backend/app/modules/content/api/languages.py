from fastapi import APIRouter, Depends

from app.bootstrap.wiring.content import get_language_catalog_service
from app.modules.content.domain.catalog import Language
from app.modules.content.application.language_catalog import LanguageCatalogService

router = APIRouter()


@router.get("/languages", response_model=list[Language])
def list_languages(
    service: LanguageCatalogService = Depends(get_language_catalog_service),
) -> list[Language]:
    return service.list_languages()
