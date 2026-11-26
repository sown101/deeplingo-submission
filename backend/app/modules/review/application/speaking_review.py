"""Project trusted independent word use into the existing recognition review card.

The database reads the committed speaking event and atomically fences the state
transition plus its per-session marker. No learner text or LLM grade enters here.
"""
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.modules.review.application.ports import SchedulingAlgorithm
from app.modules.review.domain.models import (
    ReviewEvent, ReviewGrade, ReviewState, initial_review_state, scheduling_snapshot,
    serialize_review_event_for_insert,
)


class SpeakingReviewStore(Protocol):
    def context(self, session_id: UUID, user_id: UUID, concept_id: UUID) -> dict | None: ...
    def commit(self, session_id: UUID, user_id: UUID, concept_id: UUID, transition: dict | None) -> str: ...


class SpeakingReviewService:
    def __init__(self, *, store: SpeakingReviewStore, adapter: SchedulingAlgorithm):
        self.store, self.adapter = store, adapter

    def apply(self, session_id: UUID, user_id: UUID, concept_id: UUID) -> None:
        for _ in range(3):
            context = self.store.context(session_id, user_id, concept_id)
            if context is None:
                return  # Already projected, or not a trusted independent-use event.
            when = datetime.fromisoformat(context['occurred_at'])
            state = ReviewState(**context['review_state']) if context.get('review_state') else None
            transition = None
            if context['eligible'] and (state is None or state.last_reviewed_at is None or state.last_reviewed_at < when):
                previous = state or initial_review_state(user_id=user_id, concept_id=concept_id, due_at=when)
                if previous.id is None:
                    previous = previous.model_copy(update={'id': uuid4()})
                result = self.adapter.apply(review_state=previous, grade=ReviewGrade.GOOD, reviewed_at=when)
                event = ReviewEvent(review_state_id=previous.id, review_mode=previous.review_mode,
                    rating=ReviewGrade.GOOD, previous_scheduling_state=scheduling_snapshot(previous),
                    resulting_scheduling_state=scheduling_snapshot(result.review_state), reviewed_at=when,
                    provenance='speaking_use')
                transition = {'previous': scheduling_snapshot(previous), 'next': scheduling_snapshot(result.review_state),
                              'event': serialize_review_event_for_insert(event), 'create': state is None}
            status = self.store.commit(session_id, user_id, concept_id, transition)
            if status in {'applied', 'skipped', 'duplicate'}:
                return
            if status != 'conflict':
                raise RuntimeError('Unconfirmed speaking review commit')
        raise RuntimeError('Speaking review state changed concurrently')
