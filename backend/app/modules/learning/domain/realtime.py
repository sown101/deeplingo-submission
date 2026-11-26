"""Realtime voice companion rules: limits and the post-turn transcript checks.

Speech in a realtime session cannot be validated before the learner hears it, so the server checks
each companion transcript after the turn: a grading claim ends the session; a turn outside the
language policy is a slip the agent is asked to correct (PRD 8.12 point 2). Nothing here touches
learner state.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.modules.learner.contracts import ERROR_TYPE_CODES, SIGNAL_CODES
from app.modules.learning.domain.companion import CompanionItem, reply_in_learning_script
from app.modules.learning.domain.speaking import is_grounded_quote, normalize_for_matching, primary_language

INPUT_SAMPLE_RATE = 16_000
MAX_FRAME_BYTES = INPUT_SAMPLE_RATE * 2  # at most one second of 16-bit mono audio per client frame


@dataclass(frozen=True)
class RealtimeLimits:
    max_session_seconds: int = 600
    daily_seconds_per_learner: int = 1800
    max_concurrent_sessions: int = 3
    end_of_turn_silence_ms: int = 1500


_CJK = re.compile(r"[一-鿿㐀-䶿]")
# A score, grade or level claimed for the learner (PRD principle 3). "point" alone is not one ("Good point!",
# "grammar point"); points that are counted or earned are. A word's level ("this word is HSK1") is not a claim.
_GRADING = re.compile(
    r"\b(score|scores|grade|graded|mastery|mastered|level up)\b|\b\d+\s*/\s*10\b|\bout of (10|ten)\b"
    r"|\b\d+\s*points?\b|\b(?:earn(?:ed)?|gain(?:ed)?|got|get|win|won|lose|lost)\s+(?:\w+\s+)?points?\b"
    r"|\byour (?:english |chinese |speaking )?(?:level|band|proficiency)\b"
    r"|\byou(?:'re| are| have reached| reached)(?: now| already)?(?: at)?(?: an?)?(?: level)? "
    r"(?:[abc][12]\+?|hsk ?[1-6])(?!\w)"
    r"|\byour (?:ielts|toefl)\b|\b(?:ielts|toefl)(?: score| band)(?: of| is)? ?\d|\bband (?:score )?(?:of |is )?\d"
    r"|满分|分数|得分|打分|你的\s*(?:hsk|汉语|中文|英语|口语)?\s*水平|你(?:已经)?(?:达到|是|有)了?\s*hsk\s*[1-6一二三四五六]"
    r"|trình độ (?:của )?bạn|bạn (?:đã )?(?:đạt|ở|lên)(?: được)? (?:trình độ|band|hsk|[abc][12](?!\w))"
    r"|\d+(?:[.,]\d+)?\s*điểm(?!\w)", re.IGNORECASE)


_MARKUP = re.compile(r"\*+|`+|^#+\s*", re.MULTILINE)


# Provider and system markers that are not speech: "<no speech>", "<noise>", "{pause}", "[silence]".
_MARKERS = re.compile(r"<[A-Za-z_][^<>\n]{0,39}>|\{[A-Za-z_][^{}\n]{0,39}\}"
                      r"|\[(?:no speech|noise|silence|pause|music|applause|laughter|inaudible)\]", re.IGNORECASE)
_OPEN_MARKER = re.compile(r"[<{](?:[A-Za-z_][^<>{}\n]{0,39})?$")


def strip_markers(text: str) -> str:
    """The text without provider markers; empty when nothing but markers (and spaces) was there."""
    cleaned = _MARKERS.sub("", text)
    return cleaned if cleaned == text or cleaned.strip() else ""


def hold_open_marker(text: str) -> tuple[str, str]:
    """Split off a marker still arriving in pieces ("<no sp"): (text to use now, text to keep for the next piece)."""
    found = _OPEN_MARKER.search(text)
    return (text[:found.start()], text[found.start():]) if found else (text, "")


def clean_transcript(text: str) -> str:
    """Spoken text only: no provider markers and no markdown emphasis ("**went**")."""
    return _MARKUP.sub("", strip_markers(text))


# --- Hints and corrections arrive as functions; their arguments are validated like the
# --- turn-based contract (companion-turn-v1) before the client shows them.

MAX_HINT_WORDS = 3


def hint_items(words: list[str], items: tuple[CompanionItem, ...] | list) -> list[CompanionItem]:
    """Offered items named by the hint; words outside the offered items are dropped."""
    by_text = {normalize_for_matching(item.text): item for item in items}
    chosen: list[CompanionItem] = []
    for word in words[:12]:
        item = by_text.get(normalize_for_matching(word))
        if item is not None and item not in chosen:
            chosen.append(item)
    return chosen[:MAX_HINT_WORDS]


def valid_hint(*, question: str | None, frame: str | None, frame_reason: str | None, model_sentence: str | None,
               language_code: str) -> bool:
    parts = [question, frame, model_sentence]
    if not any(part and part.strip() for part in parts):
        return False
    if any(part is not None and len(part) > 300 for part in (*parts, frame_reason)):
        return False
    if frame is not None and ("___" not in frame or not (frame_reason or "").strip()):
        return False
    if model_sentence is not None and transcript_breach(model_sentence, language_code) is not None:
        return False
    return True


def valid_correction(*, quote: str, suggestion: str, note: str, learner_said: str) -> bool:
    return (bool(learner_said.strip()) and is_grounded_quote(quote, learner_said)
            and 0 < len(suggestion.strip()) <= 200 and 0 < len(note.strip()) <= 300)


def makes_grading_claim(text: str) -> bool:
    """True when the text claims a score, grade or level for the learner (PRD principle 3)."""
    return _GRADING.search(" ".join(text.split())) is not None


def transcript_breach(reply: str, language_code: str) -> str | None:
    """A stable code when a companion utterance breaks the realtime policy, else None."""
    text = " ".join(reply.split())
    if not text:
        return None
    if makes_grading_claim(text):
        return "grading_claim"
    if not reply_in_learning_script(text):
        return "support_language"
    is_chinese = primary_language(language_code) == "zh"
    # A tool-response turn can transcribe only punctuation or numbers, with no language to check.
    if is_chinese and not _CJK.search(text) and any(character.isalpha() for character in text):
        return "wrong_language"
    if not is_chinese and _CJK.search(text):
        return "wrong_language"
    return None


def language_slip(reply: str, language_code: str, *, support_language_code: str,
                  explains_in_support: bool) -> str | None:
    """A stable code when a companion turn is outside the language policy, else None (grading is not checked here).

    The policy is the text loop's (`LevelPolicy.explains_in_support`, PRD 8.12 point 2): below B1 / HSK3 the agent
    may explain in the support language, so its script is allowed; from B1 / HSK3 only the learning language is.
    """
    text = " ".join(reply.split())
    code = transcript_breach(text, language_code)
    if code in (None, "grading_claim"):
        return None
    if not explains_in_support:
        return code
    support = primary_language(support_language_code)
    if not reply_in_learning_script(text) and support in ("en", "zh"):
        return "support_language"  # accented letters (pinyin) are not this support language
    if primary_language(language_code) != "zh" and _CJK.search(text) and support != "zh":
        return "wrong_language"
    return None  # the learning language, or the support language explaining


def valid_audio_frame(frame: bytes) -> bool:
    """16-bit little-endian mono PCM: whole samples, bounded size."""
    return 0 < len(frame) <= MAX_FRAME_BYTES and len(frame) % 2 == 0


# --- Suggestions (PRD FR-3.9) ------------------------------------------------------------------

MAX_SUGGESTIONS = 3


def valid_suggestions(raw, language_code: str) -> list[dict]:
    """At most three sayable sentences, each with a short explanation; anything else is dropped."""
    if not isinstance(raw, list):
        return []
    chosen: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        sentence, explanation = (" ".join(entry.get(key).split()) if isinstance(entry.get(key), str) else ""
                                 for key in ("sentence", "explanation"))
        if (0 < len(sentence) <= 300 and 0 < len(explanation) <= 300
                and transcript_breach(sentence, language_code) is None):
            chosen.append({"sentence": sentence, "explanation": explanation})
    return chosen[:MAX_SUGGESTIONS]


# --- Grammar teaching (PRD FR-8.1) -------------------------------------------------------------

MAX_EXPLANATION_CHARS = 600


def valid_signal(kind, code) -> tuple[str, str] | None:
    """A personalization signal the model noted: only a closed code of its kind, nothing the learner said."""
    if isinstance(kind, str) and isinstance(code, str) and code in SIGNAL_CODES.get(kind, ()):
        return kind, code
    return None


def valid_error_type(value) -> str | None:
    """The kind of mistake a correction names, only if it is one of the closed codes the agent may remember."""
    return value if isinstance(value, str) and value in ERROR_TYPE_CODES else None


def valid_grammar_explanation(explanation, example, language_code: str) -> tuple[str, str | None] | None:
    """A short explanation in the support language and, optionally, an example in the learning language."""
    text = " ".join(explanation.split()) if isinstance(explanation, str) else ""
    sample = " ".join(example.split()) if isinstance(example, str) else None
    if not 0 < len(text) <= MAX_EXPLANATION_CHARS:
        return None
    if sample:
        if len(sample) > 300 or transcript_breach(sample, language_code) is not None:
            return None
    return text, sample or None


# --- "I don't know": the learner may say plainly that they are stuck (PRD FR-3.2) --------------

_STUCK = {
    "en": ("i don't know", "i do not know", "dont know", "no idea", "i'm stuck", "im stuck", "i am stuck",
           "i can't think", "i cant think", "not sure what to say", "nothing to say"),
    "zh": ("不知道", "不会说", "我不会", "想不出", "说不出", "不知该"),
}
# Vietnamese, the support language: a stuck learner often says it there, whatever language they learn.
_STUCK_SUPPORT = ("không biết", "khong biet", "ko biết", "không nghĩ ra", "không nhớ", "quên rồi", "bí quá",
                  "bí rồi", "chịu rồi", "chịu thôi")


def says_stuck(text: str, language_code: str) -> bool:
    """True when the learner plainly says they do not know what to say; then a hint may go straight to the example."""
    lowered = " ".join(text.casefold().replace("\u2019", "'").split())
    lowered = unicodedata.normalize("NFC", lowered)
    return any(phrase in lowered for phrase in (*_STUCK.get(primary_language(language_code), ()), *_STUCK_SUPPORT))


# --- Hesitation: an utterance of fillers only (TARGET_DESIGN §7, proactive scaffolding) ------------

_FILLERS = {
    "en": {"um", "uh", "uhm", "umm", "erm", "er", "ah", "eh", "hmm", "hm", "mm", "well", "so", "like", "oh"},
    "zh": {"嗯", "呃", "额", "啊", "那个", "这个", "就是", "然后", "哦", "唔"},
}
_TOKENS = re.compile(r"[^\W_]+", re.UNICODE)


def filler_only(text: str, language_code: str) -> bool:
    """True when the learner said something, but only hesitation sounds ("um... uh", "嗯，那个")."""
    fillers = _FILLERS.get(primary_language(language_code), _FILLERS["en"]) | _FILLERS["en"]
    words = _TOKENS.findall(text.casefold())
    if not words:
        return False
    if primary_language(language_code) == "zh":
        rest = "".join(words)
        for filler in sorted(fillers, key=len, reverse=True):
            rest = rest.replace(filler, "")
        return rest == ""
    return all(word in fillers for word in words)


# --- "Why?": the learner may ask for the rule in words (PRD FR-8.1) -----------------------------

_ASKS_WHY = {
    "en": ("can you explain", "could you explain", "please explain", "explain that", "explain this", "explain why",
           "why do we", "why is", "why is it", "why does", "why did", "why don't", "why can't", "why not",
           "what's the rule", "what is the rule", "what's the grammar", "what grammar", "giải thích", "tại sao",
           "vì sao"),
    "zh": ("为什么", "请解释", "解释一下", "什么语法", "语法是", "giải thích", "tại sao"),
}


def asks_to_explain(text: str, language_code: str) -> bool:
    """True when the learner asks, in words, why something is said that way (the same as pressing Explain)."""
    lowered = " ".join(text.casefold().replace("’", "'").split())
    return any(phrase in lowered for phrase in _ASKS_WHY.get(primary_language(language_code), ()))
