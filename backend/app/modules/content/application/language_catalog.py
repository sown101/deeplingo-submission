from app.modules.content.domain.catalog import Language
from app.modules.content.application.ports import LanguageCatalogReader


class LanguageCatalogService:
    def __init__(self, languages: LanguageCatalogReader):
        self.languages = languages

    def list_languages(self) -> list[Language]:
        return self.languages.list_active()
