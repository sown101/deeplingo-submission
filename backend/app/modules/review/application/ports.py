"""Ports the review module consumes.

Each Protocol lists only the methods review calls. The composition root (bootstrap/wiring)
passes the concrete repositories/services, which satisfy them structurally.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.modules.review.domain.models import ReviewGrade, ReviewState
from app.modules.review.domain.scheduling import FSRSTransition


# --- Review-owned persistence -------------------------------------------------

class SchedulingAlgorithm(Protocol):
    """FSRS math lives only in the infrastructure FSRSAdapter."""

    def apply(self, *, review_state: ReviewState, grade: ReviewGrade,
              reviewed_at: datetime | None = None) -> FSRSTransition: ...
