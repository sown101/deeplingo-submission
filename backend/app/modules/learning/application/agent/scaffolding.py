"""Hesitation detection (PRD 8.12 point 5, TARGET_DESIGN §7): the server notices a stall, the agent chooses the help.

After the agent asks a question, a stall is five seconds of silence, an utterance of fillers only ("um", "嗯"), or
the learner saying they cannot say it. Each stall is reported to the agent with its kind and how many stalls in a row
there were for this question; the agent decides whether to wait, encourage, simplify or show a hint and how much.
At most three stalls are reported per question, so the agent is not nudged forever; when the learner really answers,
the count goes back to 0. The silence is measured from when the learner has finished hearing the agent's turn (an
estimate the channel passes in), never from when the provider finished generating it. The Hint button is a separate,
explicit request. No clock is read directly, so tests drive time with a fake clock.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from app.modules.learning.domain.realtime import filler_only, says_stuck

SILENCE_SECONDS = 5.0
MAX_STALLS = 3  # stalls reported to the agent per question


def asks_question(text: str) -> bool:
    """The agent's turn ends by asking the learner something."""
    tail = " ".join(text.split())[-3:]
    return any(mark in tail for mark in ("?", "？", "吗", "呢"))


def stall_kind(text: str, language_code: str) -> str | None:
    """"fillers" or "stuck" when the learner's utterance is a stall, else None (shared by voice and text)."""
    if filler_only(text, language_code):
        return "fillers"
    return "stuck" if says_stuck(text, language_code) else None


class Scaffolding:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, silence_seconds: float = SILENCE_SECONDS):
        self.clock = clock
        self.silence_seconds = silence_seconds
        self.level = 0  # stalls in a row for the current question (at most MAX_STALLS)
        self.hint_step = 0  # the most a hint showed for the current question: 1 question, 2 frame, 3 model answer
        self.taps = 0  # Hint presses for the current question
        self.waiting_since: float | None = None
        self.auto_hints = 0  # stalls reported to the agent in this session

    def agent_turn(self, text: str, playback_ends: float | None = None) -> None:
        """The agent finished its turn. A question, or any turn while stalls are still being reported, starts the
        silence timer once the learner has heard the turn (`playback_ends`, never earlier than now)."""
        if asks_question(text) or 0 < self.level < MAX_STALLS:
            self.waiting_since = max(self.clock(), playback_ends or 0.0)
        else:
            self.waiting_since = None

    def pause(self) -> None:
        """Someone is speaking (the learner, or the agent answering an event): no stall is measured meanwhile."""
        self.waiting_since = None

    def learner_said(self, text: str, language_code: str) -> int | None:
        """The learner's utterance ended. Fillers or "I can't say it" are a stall (its number in a row is
        returned); a real answer resets the count."""
        if stall_kind(text, language_code):
            return self._stall()
        self.level = self.hint_step = self.taps = 0
        self.waiting_since = None
        return None

    def tick(self) -> int | None:
        """Called often while the session runs: a stall number when the silence after a question has lasted."""
        if self.waiting_since is None or self.clock() - self.waiting_since < self.silence_seconds:
            return None
        return self._stall()

    def tapped(self) -> int:
        """The learner pressed Hint: an explicit request (counted for this question), not a stall."""
        self.taps += 1
        self.waiting_since = None
        return self.taps

    def hint_shown(self, step: int) -> None:
        self.hint_step = max(self.hint_step, step)

    def _stall(self) -> int | None:
        if self.level >= MAX_STALLS:
            self.waiting_since = None
            return None
        self.level += 1
        self.auto_hints += 1
        # The next stall is measured from now: another five seconds of silence is reported again.
        self.waiting_since = self.clock()
        return self.level
