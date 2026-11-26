"""Learner-facing projections of the agent's text channel. Practice only: no scores, no internals."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.learning.application.study_plan import StudyPlanItemView


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanionItemView(_View):
    id: str
    text: str
    meaning: str | None


class CompanionFrameView(_View):
    frame: str
    reason: str


class CompanionHintsView(_View):
    """The four-step ladder for the learner's next answer, opened one level at a time."""

    question: str | None
    items: list[CompanionItemView]
    frame: CompanionFrameView | None
    model_sentence: str | None


class CompanionCorrectionView(_View):
    quote: str
    suggestion: str
    note: str


class CompanionGrammarView(_View):
    """A grammar explanation the agent showed: an approved lesson, or AI-written text marked `unverified`."""

    title: str | None = None
    explanation: str
    example: str | None = None
    rules: list[str] = Field(default_factory=list)
    unverified: bool = False


class CompanionOptionView(_View):
    """One sayable sentence with a short explanation (a more natural way, or an idea for the next answer)."""

    sentence: str
    explanation: str


class CompanionSenseView(_View):
    text: str
    part_of_speech: str | None


class CompanionPracticeSuggestionView(_View):
    """M1 S3: the companion suggests one tool on one study-region line; the learner decides."""

    tool: Literal["dictation", "shadowing"]
    segment_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    reason: str


class CompanionWordView(_View):
    """A word the companion looked up: dictionary text with its source, not model text."""

    word: str
    headword: str
    senses: list[CompanionSenseView]
    source_name: str | None
    source_license: str | None
    source_url: str | None


class CompanionStudyRequestView(_View):
    """Practice the agent added to the learner's notebook (a corrected grammar point); the learner can dismiss it."""

    kind: Literal["grammar_redo", "word_review"]
    item: str
    title: str | None = None


class CompanionAudioView(_View):
    mime_type: str
    base64: str


class CompanionScenarioView(_View):
    id: str
    title: str
    context: str
    roles: list[str] = Field(min_length=2, max_length=2)
    goals: list[str] = Field(min_length=2, max_length=2)


class CompanionChoiceView(_View):
    """One thing the agent offers when the learner opened it without a topic (the client words the label)."""

    id: Literal["video", "words", "roleplay", "free"]
    count: int | None = Field(default=None, ge=1)


class CompanionActionView(_View):
    """A card the agent put on screen that does something for the learner (PRD 8.12 point 4). One shape for both channels:
    `open_review` and `open_video_region` are ready to go (the learner taps one button; nothing navigates by itself),
    `today_edited` says what changed in today's tasks and can be undone."""

    action: Literal["open_review", "open_video_region", "today_edited"]
    # open_review: exactly these saved words, in this language.
    language_code: str | None = None
    concept_ids: list[UUID] = Field(default_factory=list, max_length=20)
    # open_video_region: the learner's own video, at this part.
    library_item_id: UUID | None = None
    region_id: str | None = Field(default=None, max_length=80)
    start_ms: int | None = Field(default=None, ge=0)
    # today_edited: one task added or removed; `item_id` is what the undo call takes.
    change: Literal["added", "removed"] | None = None
    item_id: UUID | None = None
    kind: Literal["review", "conversation", "video_practice", "my_words", "add_video"] | None = None
    minutes: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=300)


class CompanionTurnView(_View):
    session_ticket: str | None = Field(description="Send back with the next turn; null when the session ended.")
    expires_at: datetime | None
    turn: int = Field(ge=0)
    max_turns: int
    finished: bool
    language_code: str
    support_language_code: str
    entry: Literal["video", "review", "home"]
    library_item_id: UUID | None
    topic: str
    learner_transcript: str | None
    reply: str
    reply_support: str
    hints: CompanionHintsView
    correction: CompanionCorrectionView | None
    used_items: list[CompanionItemView]
    next: Literal["continue", "retry", "close"]
    audio: CompanionAudioView | None
    audio_status: Literal["ready", "unavailable", "streaming"]
    follow_ups: list[StudyPlanItemView] = Field(
        default_factory=list, description="Next steps added to today's plan when the conversation ends.")
    looked_up: list[CompanionWordView] = Field(
        default_factory=list, description="Dictionary entries for a word the learner used.")
    practice_suggestion: CompanionPracticeSuggestionView | None = Field(
        default=None, description="A practice tool on one line of the study region (M1 S3); opens only on request.")
    analysis: dict | None = None
    weak_words: list[str] = Field(default_factory=list, max_length=6)
    auto_hint_level: int | None = Field(
        default=None, ge=1, le=3, description="The learner hesitated: open the hints at this step without a tap.")
    study_request: CompanionStudyRequestView | None = Field(
        default=None, description="Practice this turn added to the learner's notebook.")
    grammar: CompanionGrammarView | None = Field(
        default=None, description="A grammar explanation the agent chose to show (PRD 8.12).")
    natural: list[CompanionOptionView] = Field(
        default_factory=list, description="More natural ways to say the learner's sentence, when the agent showed them.")
    suggestions: list[CompanionOptionView] = Field(
        default_factory=list, description="Things the learner could say next, when the agent showed them.")
    choices: list[CompanionChoiceView] = Field(
        default_factory=list, description="Opening choices when no topic was chosen; the agent picks no topic.")
    actions: list[CompanionActionView] = Field(
        default_factory=list, description="Cards the agent put on screen that open something or changed today's tasks.")


class CompanionFinishView(_View):
    follow_ups: list[StudyPlanItemView] = Field(default_factory=list)
    analysis: dict | None = None
    weak_words: list[str] = Field(default_factory=list, max_length=6)
