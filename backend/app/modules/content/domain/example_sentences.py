"""Example sentences for a Concept that has no video occurrence.

An ExampleSentence is reference content, never a LearningObject. This module holds the
vendor-neutral values and the deterministic checks a generated sentence must pass before the
separate sense check (a model judgement) is even asked.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MAX_TEXT_CHARS = 240
MAX_SPACED_WORDS = 20
MIN_SPACED_WORDS = 3
MAX_UNSPACED_CHARS = 30
MIN_UNSPACED_CHARS = 4
UNSPACED_LANGUAGES = frozenset({"zh", "ja", "ko"})

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_FORBIDDEN = re.compile(r"https?:|www\.|@|[<>{}\[\]`|\\]|\n|\r", re.IGNORECASE)
_LEAKAGE = ("as an ai", "language model", "the target word", "target form", "this sentence", "dictionary sense",
            "example sentence", "sense_id", "json")


# Tatoeba sentences are CC BY 2.0 FR and shown with their author.
TATOEBA_NAME = "Tatoeba"
TATOEBA_LICENSE = "CC BY 2.0 FR"
TATOEBA_LICENSE_URL = "https://creativecommons.org/licenses/by/2.0/fr/"
TATOEBA_SENTENCE_URL = "https://tatoeba.org/en/sentences/show/{}"


class ExampleSourceKind(StrEnum):
    OCCURRENCE = "occurrence"
    DICTIONARY = "dictionary"
    CORPUS = "corpus"
    GENERATED = "generated"


class ExampleSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    concept_id: UUID
    language_code: str
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    text_key: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    target_form: str = Field(min_length=1, max_length=160)
    start_codepoint: int | None = Field(default=None, ge=0)
    end_codepoint: int | None = None
    translation: str | None = Field(default=None, min_length=1, max_length=300)
    translation_language_code: str | None = None
    source_kind: ExampleSourceKind
    source_ref: str | None = None
    license: str | None = None
    prompt_version: str | None = None
    model_name: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


def is_unspaced(language_code: str) -> bool:
    return language_code.split("-")[0].casefold() in UNSPACED_LANGUAGES


def clean_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def text_key(text: str) -> str:
    """Identity of a sentence for de-duplication: case, spacing and punctuation do not count."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(char for char in folded if char.isalnum())[:MAX_TEXT_CHARS]


def find_form_span(text: str, form: str, language_code: str) -> tuple[int, int] | None:
    """Code-point span of ``form`` in ``text`` as a whole word (or word sequence), else None."""
    needle = clean_text(form)
    if not needle:
        return None
    if is_unspaced(language_code):
        start = text.find(needle)
        return (start, start + len(needle)) if start >= 0 else None
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(part) for part in needle.split()) + r"(?!\w)"
    match = re.search(pattern, text, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def rejection_reason(text: str, form: str, language_code: str, *, gloss: str | None = None) -> str | None:
    """Why a generated sentence cannot be used, or None. Deterministic and fail-closed."""
    if not text or text != clean_text(text):
        return "not_clean"
    if len(text) > MAX_TEXT_CHARS or _FORBIDDEN.search(text):
        return "forbidden_content"
    lowered = text.casefold()
    if any(marker in lowered for marker in _LEAKAGE):
        return "prompt_leakage"
    unspaced = is_unspaced(language_code)
    if unspaced:
        if not _CJK.search(text):
            return "wrong_script"
        if not MIN_UNSPACED_CHARS <= len(text) <= MAX_UNSPACED_CHARS:
            return "length"
    else:
        if _CJK.search(text):
            return "wrong_script"
        if not MIN_SPACED_WORDS <= len(text.split()) <= MAX_SPACED_WORDS:
            return "length"
    if find_form_span(text, form, language_code) is None:
        return "target_form_missing"
    # The sentence must not hand over the dictionary gloss as the answer key.
    if gloss and len(gloss) >= 6 and gloss.casefold() in lowered:
        return "gloss_leak"
    return None
