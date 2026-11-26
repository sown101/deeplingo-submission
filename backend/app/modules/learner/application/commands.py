
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LearnerInitializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_codes: list[str] = Field(default_factory=list)
    create_profile: bool = True

    @field_validator("language_codes")
    @classmethod
    def normalize_language_codes(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for code in value:
            text = (code or "").strip().casefold()
            if not text:
                raise ValueError("language_codes cannot contain empty values")
            if text not in seen:
                normalized.append(text)
                seen.add(text)
        return normalized


class LearnerLanguageProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    learning_language: str
    support_language: str
    # L1a: the learner's own level (CEFR for English, HSK for Chinese; "" clears it) and how many
    # backlog words the daily gate activates (1 to 50).
    declared_level: str | None = None
    daily_new_limit: int | None = None

    @field_validator("learning_language", "support_language")
    @classmethod
    def normalize_language_code(cls, value: str) -> str:
        normalized = (value or "").strip().casefold()
        if not normalized:
            raise ValueError("language code cannot be empty")
        return normalized
