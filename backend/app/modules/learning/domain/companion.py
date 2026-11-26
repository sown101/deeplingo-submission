"""Voice companion rules: level policy, offered items and output checks.

The companion is non-evidential practice. These rules only decide whether a model
turn may be shown to the learner; they never touch learner state.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

from app.modules.learning.domain.speaking import (
    is_grounded_quote,
    normalize_for_matching,
    primary_language,
    spoken_unit_count,
)


class CompanionEntry(str, Enum):
    VIDEO = "video"
    REVIEW = "review"
    HOME = "home"


@dataclass(frozen=True)
class LevelPolicy:
    band: str
    # Guidance given to the model, and the hard bound a reply may not exceed. The hard
    # bound leaves a margin so a slightly long but correct reply is not discarded.
    reply_units_guidance: int
    reply_units_max: int
    max_corrections: int = 1

    @property
    def explains_in_support(self) -> bool:
        """PRD 8.12: below B1 / HSK3 the agent may explain in the learner's support language."""
        return self.band in ("A1", "A2", "HSK1", "HSK2")


# First target learners are absolute beginners (A1 / HSK1).
BEGINNER = LevelPolicy(band="A1", reply_units_guidance=12, reply_units_max=18)
BEGINNER_ZH = LevelPolicy(band="HSK1", reply_units_guidance=20, reply_units_max=30)


# The learner's declared level (levels.py) sets how long and how hard a reply may be; no declared level means
# the beginner policy. HSK and CEFR are never converted into each other.
_CEFR_POLICIES = {
    "A2": LevelPolicy(band="A2", reply_units_guidance=16, reply_units_max=24),
    "B1": LevelPolicy(band="B1", reply_units_guidance=20, reply_units_max=30),
    "B2": LevelPolicy(band="B2", reply_units_guidance=26, reply_units_max=38),
}
_CEFR_POLICIES.update({"C1": _CEFR_POLICIES["B2"], "C2": _CEFR_POLICIES["B2"]})
_HSK_POLICIES = {
    2: LevelPolicy(band="HSK2", reply_units_guidance=24, reply_units_max=36),
    3: LevelPolicy(band="HSK3", reply_units_guidance=28, reply_units_max=42),
    4: LevelPolicy(band="HSK4", reply_units_guidance=34, reply_units_max=50),
}


def level_policy(language_code: str, declared_level: str | None = None) -> LevelPolicy:
    label = (declared_level or "").strip().upper().replace(" ", "")
    if primary_language(language_code) == "zh":
        number = int(label[3:]) if label.startswith("HSK") and label[3:].isdigit() else 0
        return _HSK_POLICIES.get(min(number, 4)) or BEGINNER_ZH
    return _CEFR_POLICIES.get(label[:2]) or BEGINNER


@dataclass(frozen=True)
class CompanionItem:
    """A learning item the server offers to the companion for one session."""

    item_id: str
    text: str
    meaning: str | None
    forms: tuple[str, ...]
    practiced: bool


@dataclass(frozen=True)
class CompanionMessage:
    role: str  # "companion" | "learner"
    text: str


MAX_ITEMS = 12
MAX_TURNS = 30
MAX_HELP_REQUESTS = 20  # help buttons per text conversation (the voice channel caps its own the same way)
# The whole session (opening + learner/companion pair per turn) so the companion never
# forgets what the learner already said.
MAX_HISTORY_MESSAGES = 2 * MAX_TURNS + 1
MAX_MESSAGE_CHARS = 300
MAX_EXCERPT_CHARS = 600
MAX_COMPANION_TICKET_CHARS = 32768  # what the text routes accept as `session_ticket` (a ticket is now far shorter)

# --- M1 S3: the learner's study region as conversation context --------------------------

# A study region may hold up to 40 sentences; the prompt and ticket keep a bounded part.
MAX_REGION_LINES = 40
MAX_REGION_EXCERPT_CHARS = 2000
MAX_REGION_LINE_CHARS = 200
PRACTICE_TOOLS = ("dictation", "shadowing")


@dataclass(frozen=True)
class RegionLine:
    """One sentence of the study region, offered to the model by a short reference (s1, s2, ...)."""

    ref: str
    segment_id: str
    start_ms: int
    end_ms: int
    text: str = ""  # shown in the prompt; not kept in the ticket


@dataclass(frozen=True)
class StudyRegionContext:
    """The learner's current study region, resolved by the server from its own workspace."""

    lines: tuple[RegionLine, ...]
    before: str | None = None
    after: str | None = None


def _clock(ms: int) -> str:
    seconds = max(0, ms) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def render_region_excerpt(region: StudyRegionContext) -> tuple[str, tuple[RegionLine, ...]]:
    """Region text for the prompt and the lines it actually includes (bounded, refs kept stable)."""
    parts: list[str] = []
    kept: list[RegionLine] = []
    used = 0
    if region.before:
        before = f"(before) {' '.join(region.before.split())[:MAX_REGION_LINE_CHARS]}"
        parts.append(before)
        used += len(before) + 1
    for line in region.lines[:MAX_REGION_LINES]:
        rendered = f"[{line.ref} {_clock(line.start_ms)}] {' '.join(line.text.split())[:MAX_REGION_LINE_CHARS]}"
        if used + len(rendered) + 1 > MAX_REGION_EXCERPT_CHARS:
            break
        parts.append(rendered)
        kept.append(line)
        used += len(rendered) + 1
    if region.after and kept:
        after = f"(after) {' '.join(region.after.split())[:MAX_REGION_LINE_CHARS]}"
        if used + len(after) + 1 <= MAX_REGION_EXCERPT_CHARS:
            parts.append(after)
    return "\n".join(parts), tuple(kept)


def reply_within_policy(reply: str, language_code: str, declared_level: str | None = None) -> bool:
    text = " ".join(reply.split())
    return bool(text) and spoken_unit_count(text, language_code) <= level_policy(
        language_code, declared_level).reply_units_max


# The companion may look up one word per turn. The word must be the learner's own
# (an exact span of this turn's transcript), short, and not one of the offered items, whose
# meanings the model already has.
MAX_LOOKUP_CHARS = 40
MAX_LOOKUP_UNITS = 3
MAX_LOOKUP_UNITS_ZH = 4


def lookup_word_allowed(word: str | None, learner_said: str | None, items: tuple[CompanionItem, ...] | list,
                        language_code: str) -> str | None:
    """The cleaned word to look up, or None when the request is not allowed."""
    text = " ".join((word or "").split())
    if not text or not learner_said or len(text) > MAX_LOOKUP_CHARS:
        return None
    limit = MAX_LOOKUP_UNITS_ZH if primary_language(language_code) == "zh" else MAX_LOOKUP_UNITS
    if not 0 < spoken_unit_count(text, language_code) <= limit or not is_grounded_quote(text, learner_said):
        return None
    key = normalize_for_matching(text)
    if any(key == normalize_for_matching(form) for item in items for form in (item.text, *item.forms)):
        return None
    return text


def reply_in_learning_script(reply: str) -> bool:
    """A spoken English or Chinese reply holds no accented Latin letters.

    After a lookup the model tended to put the support-language meaning ("hàng xóm") or pinyin into
    the reply, which is spoken by the learning-language voice. Plain ASCII and Chinese characters pass.
    """
    for character in reply:
        if ord(character) < 0x80 or not unicodedata.category(character).startswith("L"):
            continue
        if not (0x4E00 <= ord(character) <= 0x9FFF or 0x3400 <= ord(character) <= 0x4DBF):
            return False
    return True


def clip_message(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= MAX_MESSAGE_CHARS else collapsed[: MAX_MESSAGE_CHARS - 1] + "…"


def data_text(text: str) -> str:
    """Text placed inside a prompt's data tags (<learner_said>, <topic>, ...) cannot close or open a tag."""
    return text.replace("<", "‹").replace(">", "›")
