from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Profile(BaseModel):
    id: UUID
    display_name: str | None = None
    timezone: str = "UTC"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserLanguagePreference(BaseModel):
    id: UUID | None = None
    user_id: UUID
    language_code: str
    support_language_code: str | None = None
    target_level: str | None = None
    declared_level: str | None = None
    daily_new_limit: int = 10
    learning_goal: str | None = None
    is_primary: bool = False
    preferences: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None


