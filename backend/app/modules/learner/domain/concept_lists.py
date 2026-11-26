"""The learner's "My words".

A saved word is a learner request: it raises practice priority and nothing else.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ConceptList(str, Enum):
    SAVED = "saved"


class SaveSource(str, Enum):
    LOOKUP = "lookup"
    MANUAL = "manual"
    OCCURRENCE = "occurrence"
    IMPORT = "import"
    CONTENT = "content"


class SavedWord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    concept_id: UUID
    note: str | None = None
    favorite: bool = False
    save_source: SaveSource | None = None
    created_at: datetime | None = None
    # L1a: the same row is the learner's target (status, priority, level, ladder rung).
    status: str = "active"
    explicit: bool = True
    priority: int = 0
    level_label: str | None = None
    rung: int = 0
    activated_at: datetime | None = None
    language_code: str | None = None
