from datetime import datetime

from app.modules.review.domain.models import ReviewState


class FSRSTransition:
    def __init__(self, *, previous_state: ReviewState, review_state: ReviewState, reviewed_at: datetime):
        self.previous_state = previous_state
        self.review_state = review_state
        self.reviewed_at = reviewed_at
