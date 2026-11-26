"""Vendor-neutral Content execution failure policy (not learner assessment)."""
from dataclasses import dataclass
from enum import Enum


class ContentFailureClass(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ContentFailure:
    category: ContentFailureClass
    code: str
    explicit_retry: bool = False
