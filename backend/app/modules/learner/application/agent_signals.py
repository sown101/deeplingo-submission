"""The learner's one revocable voice consent and the personalization signals the agent keeps.

Signals are written only for a learner who granted consent and only as closed codes; the
learner can read and delete them at any time, including after revoking consent.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.learner.domain.agent_signals import (
    SINGLE_VALUE_KINDS,
    PersonalizationSignal,
    SignalKind,
    consent_status,
    is_allowed,
)


class AgentConsentView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str  # "ask" | "granted" | "revoked"
    decided_at: str | None


class SignalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    language_code: str
    kind: SignalKind
    code: str
    usage_count: int
    updated_at: str | None


class SignalsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signals: list[SignalView]


def _signal_view(signal: PersonalizationSignal) -> SignalView:
    return SignalView(
        id=signal.id, language_code=signal.language_code, kind=signal.kind, code=signal.code,
        usage_count=signal.usage_count, updated_at=signal.updated_at.isoformat() if signal.updated_at else None,
    )


class AgentSignalsService:
    def __init__(self, *, consents, signals):
        self.consents = consents
        self.store = signals

    def consent(self, user_id: UUID) -> AgentConsentView:
        row = self.consents.get(user_id)
        return AgentConsentView(status=consent_status(row),
                                decided_at=row.decided_at.isoformat() if row and row.decided_at else None)

    def has_consent(self, user_id: UUID) -> bool:
        return consent_status(self.consents.get(user_id)) == "granted"

    def set_consent(self, user_id: UUID, granted: bool) -> AgentConsentView:
        self.consents.set(user_id, granted)
        return self.consent(user_id)

    def signals(self, user_id: UUID) -> SignalsView:
        # Shown whatever the consent says, so a learner who revoked can still look and delete.
        rows = [row for row in self.store.list_all(user_id) if row.id is not None]
        return SignalsView(signals=[_signal_view(row) for row in rows])

    def delete_one(self, user_id: UUID, signal_id: UUID) -> bool:
        return self.store.delete_one(user_id, signal_id)

    def delete_all(self, user_id: UUID) -> None:
        self.store.delete_all(user_id)

    def record(self, user_id: UUID, *, language_code: str, kind: SignalKind, code: str) -> bool:
        """Store one closed-code signal; False (and nothing stored) without consent or for any other code."""
        if not is_allowed(kind, code) or not self.has_consent(user_id):
            return False
        self.store.record(user_id, language_code=language_code, kind=kind, code=code,
                          replace_kind=kind in SINGLE_VALUE_KINDS)
        return True
