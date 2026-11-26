"""Self-service account deletion (PRD FR-6.1): one confirmed request deletes the learner's own account.

Everything that belongs to the learner is removed with the sign-in user (their rows cascade from it).
Shared content, such as videos, transcripts and dictionaries, is never touched here.
"""
from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

logger = logging.getLogger(__name__)

CONFIRMATION = "DELETE"


class AccountDeletionError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SignInUsers(Protocol):
    def delete_user(self, user_id: UUID) -> None: ...


class AccountDeletionService:
    def __init__(self, *, users: SignInUsers):
        self.users = users

    def delete(self, user_id: UUID, confirm: str | None) -> None:
        if confirm != CONFIRMATION:
            raise AccountDeletionError(f"Type {CONFIRMATION} to confirm.", status_code=422,
                                       code="account_deletion_not_confirmed")
        try:
            self.users.delete_user(user_id)
        except Exception as exc:
            # The provider's message may name internals; log only its type.
            logger.warning("account deletion failed error=%s", type(exc).__name__)
            raise AccountDeletionError("Your account could not be deleted right now. Please try again.",
                                       status_code=503, code="account_deletion_unavailable") from exc
