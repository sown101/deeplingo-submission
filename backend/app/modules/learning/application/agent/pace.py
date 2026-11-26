"""Delivery during a conversation (agent harness plan, phase 6; after Mural's ConversationPace).

The level's language policy says how the agent speaks at the start. During the conversation the server watches what
it can check about each learner turn (a stall, a help request, how much the learner said on their own) and, when the
picture changes, tells the agent once: speak more gently, naturally, or invite longer answers. The note is guidance
for the next replies only; the agent decides, and it never changes saved progress.
"""
from __future__ import annotations

from typing import Literal

from app.modules.learning.application.speaking_signals import turn_units

Delivery = Literal["gentle", "natural", "extended"]

# A turn the learner said on their own counts as a success when it has at least this many words (characters in
# Chinese); a long one when it has at least the second number.
_SUCCESS_UNITS = {"zh": (6, 14)}
_DEFAULT_UNITS = (5, 12)
SUCCESSES_TO_RISE = 2

_GUIDANCE = {
    "gentle": "Use one short sentence at a time, familiar words and a calm pace. Leave space to answer.",
    "natural": "Use one or two short sentences at a clear, natural pace. Ask a follow-up that lets the learner expand.",
    "extended": "Use natural connected sentences. Invite reasons or a short story, and keep each turn concise.",
}


def pace_note(delivery: Delivery) -> str:
    return (f"(Delivery for your next replies, from how the learner is doing: {_GUIDANCE[delivery]} This is provisional: "
            "simplify at once if they struggle. Never read this note aloud.)")


def observe(session, said: str, language_code: str, *, stalled: bool, helped: bool) -> Delivery | None:
    """One finished learner turn; returns the new delivery when it changed (the note to send), else None."""
    if stalled or helped:
        session.pace_successes = session.pace_long = 0
        return _set(session, "gentle")
    low, high = _SUCCESS_UNITS.get(language_code.split("-")[0], _DEFAULT_UNITS)
    units = turn_units(said, language_code)
    if units < low:
        session.pace_successes = session.pace_long = 0
        return None
    session.pace_successes += 1
    session.pace_long = session.pace_long + 1 if units >= high else 0
    if session.pace_long >= SUCCESSES_TO_RISE:
        return _set(session, "extended")
    if session.pace_successes >= SUCCESSES_TO_RISE:
        return _set(session, "natural" if session.pace != "extended" else "extended")
    return None


def _set(session, delivery: Delivery) -> Delivery | None:
    # The start is the level policy's delivery ("natural" or simpler): the first note is a change from it.
    current = session.pace or "natural"
    if delivery == current:
        session.pace = delivery
        return None
    session.pace = delivery
    return delivery
