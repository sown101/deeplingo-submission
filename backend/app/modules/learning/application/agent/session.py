"""AgentSession: one conversation with Tata, whatever the channel (TARGET_DESIGN §7).

A small state machine: greeting -> practice -> wrap_up -> ended, in one of four modes: `region` (a video part
the learner studies), `topic` (free talk about a topic or the words due), `roleplay` (a server-owned situation),
`open` (nothing chosen yet: the agent asks what the learner wants and offers choices; it picks no topic).
`start_roleplay` switches the mode during practice. The session holds what the server must decide on its own:
hesitation (Scaffolding), how often the learner asked for help, what was shown, the closed codes noticed and
the support delivered (so a copied hint never counts as independent use). Voice and text are adapters around it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from app.modules.learning.application.agent.context import LearnerContext
from app.modules.learning.application.agent.scaffolding import Scaffolding
from app.modules.learning.application.session_events import LearnerTurn, contains_form
from app.modules.learning.domain.companion import CompanionMessage

Mode = Literal["region", "topic", "roleplay", "open"]
MAX_EXAMPLES = 80
# Support is kept whole up to this length so a copied answer can still be found in it; an explanation in the
# support language (60 words) or a grammar summary (600 characters) fits. Longer support cannot be checked.
MAX_SUPPORT_CHARS = 600


class Phase(str, Enum):
    GREETING = "greeting"
    PRACTICE = "practice"
    WRAP_UP = "wrap_up"
    ENDED = "ended"


def mode_of(ticket) -> Mode:
    if getattr(ticket, "scenario_id", None):
        return "roleplay"
    return "region" if getattr(ticket, "region_lines", ()) else "topic"


@dataclass
class AgentSession:
    user: object
    prepared: object  # PreparedConversation: the server-built context of this conversation
    day: date | None = None
    started: float = 0.0
    transient: bool = False  # the agent chose the words to practise (selected-word evidence)
    # The learner's voice consent, rechecked when the session ends (they may revoke it meanwhile).
    consented: bool = True
    id: UUID = field(default_factory=uuid4)
    phase: Phase = Phase.GREETING
    mode: Mode | None = None
    scaffolding: Scaffolding = field(default_factory=Scaffolding)
    context: LearnerContext | None = None
    lesson_menu: object | None = None  # a LessonMenu, or False once it could not be built
    history: list[CompanionMessage] = field(default_factory=list)
    learner_turn: list[str] = field(default_factory=list)
    companion_turn: list[str] = field(default_factory=list)
    end_reason: str | None = None
    breach: str | None = None
    # PRD 8.12: on both channels the agent may show help nobody asked for (hint, ideas, a more natural way, a
    # grammar explanation) and chooses how much a hint gives. A help button is an explicit request sent to the agent.
    help_requests: int = 0
    explain_asked: bool = False  # the learner asked "why?" aloud in this turn (voice)
    auto_hint_pending: bool = False  # the agent was last told of a stall, not of a Hint press
    # What was shown and noticed (counts and closed codes only).
    turns: int = 0
    learner_turns: int = 0
    hints: int = 0
    corrections: int = 0
    suggestions: int = 0
    rejected_calls: int = 0
    tool_calls: int = 0  # every tool call of the conversation (AgentCore limits it)
    turn_tool_calls: int = 0  # the current agent turn's calls
    language_slips: int = 0  # agent turns in a row outside the language policy (voice)
    # Delivery during the conversation (pace.py): the last one the agent was told, and the learner's turns in a row
    # said on their own (long ones counted apart).
    pace: str | None = None
    pace_successes: int = 0
    pace_long: int = 0
    error_codes: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    reuse_words: list[str] = field(default_factory=list)
    tasks_shown: bool = False
    choices: list[dict] = field(default_factory=list)  # the opening choices still on offer (mode "open")
    study_requests: int = 0
    memories: int = 0  # things the agent remembered in this conversation (at most three)
    # A channel that can fail a turn after the agent used a tool (text) keeps what the agent remembers or forgets here
    # and writes it once the turn is spent; the voice channel writes at once.
    defer_memory: bool = False
    memory_ops: list[tuple] = field(default_factory=list)
    today_edits: int = 0  # changes the agent made to today's tasks in this conversation (at most three)
    redo_points: set[str] = field(default_factory=set)
    looked_up: dict[str, list] = field(default_factory=dict)  # word -> dictionary entries shown this session
    # Support delivered to the learner, for word-use evidence (FR-3.5).
    analysis_turns: list[LearnerTurn] = field(default_factory=list)
    assisted_ids: set[UUID] = field(default_factory=set)
    examples: list[str] = field(default_factory=list)
    support_truncated: bool = False

    def __post_init__(self) -> None:
        if self.mode is None:
            self.mode = mode_of(self.ticket)

    @property
    def ticket(self):
        return self.prepared.ticket

    @property
    def tracks(self) -> bool:
        """Learner turns and prior support are recorded while the learner's consent stands."""
        return self.transient or self.consented

    @property
    def help_level(self) -> int:
        """How much help the current question has had (0-3), as kept with a learner turn (FR-3.11) and logged: the
        most a hint showed (1 question, 2 frame, 3 model answer), or the Hint presses and stalls reported if more."""
        scaffolding = self.scaffolding
        return min(3, max(scaffolding.hint_step, scaffolding.taps, scaffolding.level))

    # --- State machine ---------------------------------------------------------------------

    def learner_spoke(self) -> None:
        self.choices = []
        if self.phase == Phase.GREETING:
            self.phase = Phase.PRACTICE

    def start_roleplay(self) -> None:
        self.mode = "roleplay"
        self.phase = Phase.PRACTICE

    def wrap_up(self, reason: str | None = None) -> None:
        if self.phase != Phase.ENDED:
            self.phase = Phase.WRAP_UP
        self.end_reason = self.end_reason or reason

    def end(self) -> None:
        self.phase = Phase.ENDED

    # --- Turn facts ------------------------------------------------------------------------

    def learner_said(self) -> str:
        """This turn's words, or the learner's last turn when a tool call arrives after it."""
        current = " ".join("".join(self.learner_turn).split())
        return current or next((message.text for message in reversed(self.history) if message.role == "learner"), "")

    def note_support(self, text: str | None) -> None:
        """Everything shown or said to the learner counts as support for the words it contains."""
        if not self.tracks or not text:
            return
        collapsed = " ".join(text.split())
        if len(collapsed) > MAX_SUPPORT_CHARS or len(self.examples) >= MAX_EXAMPLES:
            self.support_truncated = True
        if len(self.examples) < MAX_EXAMPLES:
            self.examples.append(collapsed[:MAX_SUPPORT_CHARS])
        ticket = self.ticket
        for item in ticket.items:
            if any(contains_form(text, form, ticket.language_code) for form in item.forms):
                self.assisted_ids.add(UUID(item.item_id))
