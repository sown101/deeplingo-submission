from uuid import UUID

from pydantic import BaseModel



class LearnerInitializationResult(BaseModel):
    user_id: UUID
    profile_status: str


class LearnerLanguageProfile(BaseModel):
    learning_language: str | None = None
    support_language: str | None = None
    is_complete: bool = False
    declared_level: str | None = None
    daily_new_limit: int = 10
