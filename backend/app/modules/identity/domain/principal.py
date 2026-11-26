from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CurrentUser(BaseModel):
    """Authenticated Supabase identity for request-scoped authorization."""

    id: UUID
    role: str = "authenticated"
    email: str | None = None
    claims: dict[str, Any] = Field(default_factory=dict, exclude=True)
