"""Public surface of the learner module."""
from app.modules.learner.domain.models import (
    Profile,
    UserLanguagePreference,
)
from app.modules.learner.domain.agent_signals import ALLOWED_CODES, SignalKind

# The kinds of grammar mistake the agent may remember (closed codes, never sentences).
ERROR_TYPE_CODES = ALLOWED_CODES[SignalKind.ERROR_TYPE]
# Every kind of personalization signal with its closed codes.
SIGNAL_CODES = {kind.value: codes for kind, codes in ALLOWED_CODES.items()}
