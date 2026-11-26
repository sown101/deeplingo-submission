"""The exercise engine for words (TARGET_DESIGN section 5): one generator and one grader per exercise type.

Every exercise is built on the server from what the server knows about the word (`WordCard`); the client gets
the prompt only. The grader works from the same card, never from anything the client says about the answer.
Generators raise `ExerciseUnavailable` when a good question cannot be built (no meaning, no sentence that holds
the word once, too few other words for options); the caller then falls back to another type.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from app.modules.practice.domain.meaning_choices import QuickReviewQuestionUnavailable, pick_meaning_distractors

ExerciseType = Literal["flashcard", "choice", "listening", "cloze", "pronunciation", "writing", "match", "order"]
EXERCISE_TYPES: tuple[str, ...] = ExerciseType.__args__
# Practice only (owner decision 2026-11-14): graded and logged, but they never move the FSRS schedule.
UNSCHEDULED_TYPES = frozenset({"pronunciation", "writing"})
# What a session of mixed exercises cycles through; pronunciation needs a microphone and writing needs Han
# characters, so both are chosen on purpose.
MIXED_ORDER: tuple[str, ...] = ("choice", "listening", "cloze", "flashcard")
FALLBACK: tuple[str, ...] = ("choice", "flashcard")
LISTENING_OPTIONS = 4
MIN_ORDER_PARTS = 3
MAX_ORDER_PARTS = 12
MAX_ORDER_CHARACTERS = 8
MAX_SENTENCE_CHARS = 240
BLANK = "____"
# Scripts written stroke by stroke with hanzi-writer.
STROKE_LANGUAGES = frozenset({"zh", "ja"})


class ExerciseUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class SentenceSource:
    """A sentence holding the word: from the learner's own video first, else a stored example."""
    text: str
    target_form: str
    origin: Literal["video", "example"]
    library_item_id: UUID | None = None
    start_ms: int | None = None


@dataclass(frozen=True)
class WordCard:
    """What the server knows about one saved word in the learner's support language."""
    concept_id: UUID
    language_code: str
    text: str
    reading: str | None = None
    meaning: str | None = None
    part_of_speech: str | None = None
    sentence: SentenceSource | None = None
    other_forms: tuple[str, ...] = ()


@dataclass(frozen=True)
class Exercise:
    type: str
    prompt: dict[str, Any]


@dataclass(frozen=True)
class Graded:
    correct: bool
    outcome: str  # learning-log outcome: correct / incorrect / partial
    expected: str  # what the right answer was, shown after the answer
    detail: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


def base_language(code: str) -> str:
    return code.split("-")[0].casefold()


def fold(text: str) -> str:
    """NFKC, case, spacing and closing punctuation do not count; marks count."""
    value = unicodedata.normalize("NFKC", text or "").casefold().strip()
    value = " ".join(value.split())
    return re.sub(r"[\s.!?。！？]+$", "", value)


def _fold_written(text: str, language_code: str) -> str:
    value = fold(text)
    if base_language(language_code) in STROKE_LANGUAGES:
        value = value.replace(" ", "")  # spaces between Han characters carry nothing
    return value


def _order(seed: str, values: list[str]) -> list[str]:
    return sorted(values, key=lambda value: hashlib.sha256(f"{seed}:{value}".encode()).hexdigest())


def mask_sentence(sentence: SentenceSource, language_code: str) -> str:
    """The sentence with its one occurrence of the word blanked out."""
    text, target = " ".join(sentence.text.split()), sentence.target_form.strip()
    if not text or not target or len(text) > MAX_SENTENCE_CHARS or BLANK in text:
        raise ExerciseUnavailable("no_sentence")
    pattern = re.escape(target)
    if base_language(language_code) not in STROKE_LANGUAGES:
        pattern = rf"(?<!\w){pattern}(?!\w)"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))
    if len(matches) != 1:
        raise ExerciseUnavailable("ambiguous_blank")
    match = matches[0]
    rest = text[:match.start()] + text[match.end():]
    if not any(char.isalnum() for char in rest):
        raise ExerciseUnavailable("no_context")
    return text[:match.start()] + BLANK + text[match.end():]


# --- Generators ------------------------------------------------------------------------------------------------

def _sentence_view(sentence: SentenceSource | None) -> dict[str, Any] | None:
    if sentence is None:
        return None
    view: dict[str, Any] = {"text": sentence.text, "origin": sentence.origin}
    if sentence.library_item_id is not None:
        view.update(library_item_id=str(sentence.library_item_id), start_ms=sentence.start_ms or 0)
    return view


def flashcard(card: WordCard) -> Exercise:
    return Exercise("flashcard", {"text": card.text, "reading": card.reading, "meaning": card.meaning,
                                  "sentence": _sentence_view(card.sentence)})


def choice(card: WordCard, meaning_pool: list[tuple], *, seed: str) -> Exercise:
    """Choose the meaning: the word's own meaning and two other words' meanings in the same language."""
    if not card.meaning:
        raise ExerciseUnavailable("no_meaning")
    try:
        others = pick_meaning_distractors(correct=card.meaning, headword=card.text, pool=meaning_pool,
                                          order_seed=seed, part_of_speech=card.part_of_speech)
    except QuickReviewQuestionUnavailable as exc:
        raise ExerciseUnavailable("not_enough_options") from exc
    sentence = card.sentence.text if card.sentence is not None else None
    return Exercise("choice", {"text": card.text, "reading": card.reading, "sentence": sentence,
                               "options": _order(seed, [card.meaning, *others])})


def listening(card: WordCard, word_pool: list[str], *, seed: str) -> Exercise:
    """Hear the word, choose it among other words of the same language. The audio is fetched by concept id."""
    own = fold(card.text)
    others: list[str] = []
    for word in _order(seed, [" ".join(word.split()) for word in word_pool if word and word.strip()]):
        if fold(word) != own and all(fold(word) != fold(other) for other in others):
            others.append(word)
        if len(others) == LISTENING_OPTIONS - 1:
            break
    if len(others) < 2:
        raise ExerciseUnavailable("not_enough_options")
    return Exercise("listening", {"options": _order(seed, [card.text, *others])})


def cloze(card: WordCard) -> Exercise:
    """Fill the word into a sentence, from the learner's own video first; the meaning is the cue."""
    if card.sentence is None:
        raise ExerciseUnavailable("no_sentence")
    masked = mask_sentence(card.sentence, card.language_code)
    return Exercise("cloze", {"sentence": masked, "meaning": card.meaning,
                              "source": _sentence_view(card.sentence) | {"text": masked}})


def pronunciation(card: WordCard) -> Exercise:
    return Exercise("pronunciation", {"text": card.text, "reading": card.reading, "meaning": card.meaning})


def writing(card: WordCard) -> Exercise:
    """Han characters are written stroke by stroke over the character (hanzi-writer). Latin-script words have no
    writing practice (owner decision 2026-11-15)."""
    if base_language(card.language_code) not in STROKE_LANGUAGES:
        raise ExerciseUnavailable("not_han_characters")
    characters = [char for char in card.text if unicodedata.name(char, "").startswith(("CJK UNIFIED", "CJK COMPAT"))]
    if not characters or len(characters) != len(card.text.replace(" ", "")):
        raise ExerciseUnavailable("not_han_characters")
    return Exercise("writing", {"script": "strokes", "characters": card.text.replace(" ", ""),
                                "reading": card.reading, "meaning": card.meaning})


def match(card: WordCard) -> Exercise:
    """One pair of a match-the-meanings board: the client puts several cards' words and meanings side by side and
    sends each pairing as the meaning chosen for that word."""
    if not card.meaning:
        raise ExerciseUnavailable("no_meaning")
    return Exercise("match", {"text": card.text, "reading": card.reading, "meaning": card.meaning})


def _is_han(char: str) -> bool:
    return unicodedata.name(char, "").startswith(("CJK UNIFIED", "CJK COMPAT"))


def order_parts(card: WordCard) -> tuple[str, list[str]]:
    """What "put it in order" asks for: the word's sentence (3 to 12 words; Han text by character), else the
    characters of a Chinese or Japanese word of two or more characters."""
    stroke = base_language(card.language_code) in STROKE_LANGUAGES
    if card.sentence is not None and len(card.sentence.text) <= MAX_SENTENCE_CHARS:
        if stroke:
            parts = [char for char in card.sentence.text if char.isalnum()]
        else:
            parts = [part for part in (re.sub(r"^\W+|\W+$", "", word) for word in card.sentence.text.split()) if part]
        if MIN_ORDER_PARTS <= len(parts) <= MAX_ORDER_PARTS:
            return "sentence", parts
    characters = [char for char in card.text if not char.isspace()]
    if stroke and 2 <= len(characters) <= MAX_ORDER_CHARACTERS and all(_is_han(char) for char in characters):
        return "characters", characters
    raise ExerciseUnavailable("nothing_to_order")


def join_parts(parts: list[str], language_code: str) -> str:
    return ("" if base_language(language_code) in STROKE_LANGUAGES else " ").join(parts)


def order(card: WordCard, *, seed: str) -> Exercise:
    kind, parts = order_parts(card)
    shuffled = [parts[int(index)] for index in _order(seed, [str(index) for index in range(len(parts))])]
    if shuffled == parts:  # never hand out the answer already in order
        shuffled = shuffled[1:] + shuffled[:1]
    return Exercise("order", {"kind": kind, "parts": shuffled, "meaning": card.meaning})


def generate(exercise_type: str, card: WordCard, *, meaning_pool: list[tuple], word_pool: list[str],
             seed: str) -> Exercise:
    if exercise_type == "flashcard":
        return flashcard(card)
    if exercise_type == "choice":
        return choice(card, meaning_pool, seed=seed)
    if exercise_type == "listening":
        return listening(card, word_pool, seed=seed)
    if exercise_type == "cloze":
        return cloze(card)
    if exercise_type == "pronunciation":
        return pronunciation(card)
    if exercise_type == "writing":
        return writing(card)
    if exercise_type == "match":
        return match(card)
    if exercise_type == "order":
        return order(card, seed=seed)
    raise ExerciseUnavailable("unknown_type")


def generate_with_fallback(exercise_type: str, card: WordCard, *, fallback: tuple[str, ...] = FALLBACK,
                           **pools) -> Exercise:
    """The asked type, else the fallback types in turn (by default choose-the-meaning, else a flashcard, which needs
    only the word)."""
    for candidate in dict.fromkeys((exercise_type, *fallback)):
        try:
            return generate(candidate, card, **pools)
        except ExerciseUnavailable:
            continue
    raise ExerciseUnavailable("no_exercise")


# --- Graders ---------------------------------------------------------------------------------------------------

def _graded(correct: bool, expected: str, **detail) -> Graded:
    return Graded(correct=correct, outcome="correct" if correct else "incorrect", expected=expected, detail=detail)


def grade_choice(card: WordCard, answer: dict[str, Any]) -> Graded:
    if not card.meaning:
        raise ExerciseUnavailable("no_meaning")
    option = answer.get("option")
    correct = not answer.get("dont_know") and isinstance(option, str) and fold(option) == fold(card.meaning)
    return _graded(correct, card.meaning)


def grade_listening(card: WordCard, answer: dict[str, Any]) -> Graded:
    option = answer.get("option")
    return _graded(isinstance(option, str) and fold(option) in {fold(card.text), *map(fold, card.other_forms)},
                   card.text)


def grade_cloze(card: WordCard, answer: dict[str, Any]) -> Graded:
    text = answer.get("text")
    forms = {card.text, *card.other_forms, *([card.sentence.target_form] if card.sentence else [])}
    expected = card.sentence.target_form if card.sentence else card.text
    return _graded(isinstance(text, str) and _fold_written(text, card.language_code)
                   in {_fold_written(form, card.language_code) for form in forms}, expected)


def grade_writing(card: WordCard, answer: dict[str, Any]) -> Graded:
    if base_language(card.language_code) not in STROKE_LANGUAGES:
        raise ExerciseUnavailable("not_han_characters")
    text = answer.get("text")
    forms = {_fold_written(form, card.language_code) for form in (card.text, *card.other_forms)}
    correct = isinstance(text, str) and _fold_written(text, card.language_code) in forms
    mistakes = answer.get("mistakes")
    detail: dict[str, Any] = {}
    if isinstance(mistakes, int) and not isinstance(mistakes, bool) and mistakes >= 0:
        detail["mistakes"] = min(mistakes, 999)
    return _graded(correct, card.text, **detail)


MAX_STORED_ASSESSMENT_CHARS = 1100  # the learning log keeps a small detail object (2 KB in the database)


def compact_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    """The assessment as the learning log keeps it: no recognised text; phonemes, then words, are dropped when it
    would not fit."""
    kept = {key: value for key, value in assessment.items() if key != "recognized_text"}
    size = lambda value: len(json.dumps(value, ensure_ascii=False))  # noqa: E731
    if size(kept) > MAX_STORED_ASSESSMENT_CHARS:
        kept["words"] = [{**word, "phonemes": []} for word in kept.get("words") or []]
    if size(kept) > MAX_STORED_ASSESSMENT_CHARS:
        kept["words"] = []
    return kept


def grade_pronunciation(card: WordCard, *, band: str, score: float,
                        assessment: dict[str, Any] | None = None) -> Graded:
    """Azure's band, as the learner already sees it: good or excellent is right, fair is right with help. The whole
    assessment (scores, words, phonemes) is kept in the detail."""
    correct = band in {"good", "excellent", "fair"}
    outcome = "partial" if band == "fair" else ("correct" if correct else "incorrect")
    detail: dict[str, Any] = {"band": band}
    if assessment:
        detail["assessment"] = compact_assessment(assessment)
    return Graded(correct=correct, outcome=outcome, expected=card.text, score=round(float(score), 1),
                  detail=detail)


def grade_order(card: WordCard, answer: dict[str, Any]) -> Graded:
    """The parts as the learner put them, joined; spacing, case and closing punctuation do not count."""
    _, parts = order_parts(card)
    expected = join_parts(parts, card.language_code)
    text = answer.get("text")
    correct = isinstance(text, str) and (_fold_written(text, card.language_code)
                                         == _fold_written(expected, card.language_code))
    return _graded(correct, expected)


def grade_flashcard(card: WordCard, answer: dict[str, Any]) -> Graded:
    rating = answer.get("rating")
    outcome = {"again": "incorrect", "not_yet": "incorrect", "hard": "partial", "unsure": "partial"}.get(
        rating, "correct")
    return Graded(correct=outcome == "correct", outcome=outcome, expected=card.meaning or card.text,
                  detail={"rating": rating})


def grade(exercise_type: str, card: WordCard, answer: dict[str, Any]) -> Graded:
    if exercise_type in {"choice", "match"}:
        return grade_choice(card, answer)
    if exercise_type == "order":
        return grade_order(card, answer)
    if exercise_type == "listening":
        return grade_listening(card, answer)
    if exercise_type == "cloze":
        return grade_cloze(card, answer)
    if exercise_type == "writing":
        return grade_writing(card, answer)
    if exercise_type == "flashcard":
        return grade_flashcard(card, answer)
    raise ExerciseUnavailable("unknown_type")  # pronunciation is graded from audio, see grade_pronunciation
