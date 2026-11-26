"""Tatoeba sentences (CC BY 2.0 FR, https://tatoeba.org).

Parses the per-language exports (`<lang>_sentences_detailed.tsv.bz2`, `vie_sentences.tsv.bz2`
and the `<lang>-vie_links.tsv.bz2` link files) and keeps a bounded subset of short, everyday
sentences for learners. Nothing here touches the database.
"""
from __future__ import annotations

import bz2
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

LICENSE = "CC BY 2.0 FR"
SOURCE = "tatoeba"
LANGUAGE_CODES = {"eng": "en", "cmn": "zh", "vie": "vi"}
MAX_AUTHOR_CHARS = 80

_EN_ALLOWED = re.compile(r"^[A-Za-z][A-Za-z ,.'?!-]*[.?!]$")
_ZH_ALLOWED = re.compile(r"^[一-鿿。，？！、]+$")
# Common characters that exist only in Traditional Chinese. DeepLingo teaches Simplified
# (CC-CEDICT headwords), and the export mixes both scripts without a label.
_TRADITIONAL_ONLY = frozenset(
    "們說這個來時對學會點裡從過還讓開關門間問題見話為與兩讀書國電車黨義務應該機經語長買賣誰請錯認識體現實"
    "愛歡難歲鳥魚專業東區醫園樂鐘錶線結給麼處爲裏邊帶幫總變讓聽報紙樣辦個氣歷點師條場關幾幹單準備"
)


@dataclass(frozen=True)
class CorpusRow:
    source_id: int
    language_code: str
    text: str
    author: str | None
    translations: dict[str, str] = field(default_factory=dict)

    def as_record(self) -> dict:
        return {
            "source": SOURCE, "source_id": self.source_id, "language_code": self.language_code,
            "text": self.text, "author": self.author, "license": LICENSE,
            "translations": self.translations,
        }


def read_tsv(path: str | Path) -> Iterator[list[str]]:
    with bz2.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            yield line.rstrip("\r\n").split("\t")


def is_learner_sentence(text: str, language_code: str) -> bool:
    """A short, plain, self-contained sentence a beginner can read."""
    if language_code == "en":
        words = text.split()
        return 4 <= len(words) <= 10 and len(text) <= 70 and bool(_EN_ALLOWED.match(text))
    if language_code == "zh":
        return (5 <= len(text) <= 24 and bool(_ZH_ALLOWED.match(text))
                and not any(char in _TRADITIONAL_ONLY for char in text))
    return False


def _author(raw: str | None) -> str | None:
    value = (raw or "").strip()
    return value[:MAX_AUTHOR_CHARS] if value and value != "\\N" else None


def read_sentences(path: str | Path, language_code: str) -> dict[int, tuple[str, str | None]]:
    """id -> (text, author) for the sentences a learner could use, de-duplicated by text."""
    found: dict[int, tuple[str, str | None]] = {}
    seen: set[str] = set()
    for row in read_tsv(path):
        if len(row) < 3 or not row[0].isdigit():
            continue
        text = " ".join(row[2].split())
        key = text.casefold()
        if key in seen or not is_learner_sentence(text, language_code):
            continue
        seen.add(key)
        found[int(row[0])] = (text, _author(row[3] if len(row) > 3 else None))
    return found


def read_all_sentences(path: str | Path) -> dict[int, str]:
    """id -> text for a translation language, without learner filtering."""
    return {int(row[0]): " ".join(row[2].split()) for row in read_tsv(path)
            if len(row) >= 3 and row[0].isdigit() and row[2].strip()}


def read_links(path: str | Path) -> dict[int, list[int]]:
    links: dict[int, list[int]] = {}
    for row in read_tsv(path):
        if len(row) >= 2 and row[0].isdigit() and row[1].isdigit():
            links.setdefault(int(row[0]), []).append(int(row[1]))
    return links


def select_rows(
    sentences: dict[int, tuple[str, str | None]], language_code: str, *,
    links: dict[int, list[int]], translations: dict[int, str], translation_language: str, cap: int,
) -> list[CorpusRow]:
    """Sentences with a translation first, then the shortest; at most ``cap`` of them."""
    rows = []
    for source_id, (text, author) in sentences.items():
        translated = next((translations[target] for target in links.get(source_id, []) if target in translations), None)
        rows.append(CorpusRow(source_id, language_code, text, author,
                              {translation_language: translated[:300]} if translated else {}))
    rows.sort(key=lambda row: (not row.translations, len(row.text), row.source_id))
    return rows[:cap]


def summarize(rows: list[CorpusRow]) -> dict:
    size = sum(len(row.text.encode("utf-8")) + len((row.author or "").encode("utf-8"))
               + sum(len(value.encode("utf-8")) for value in row.translations.values()) + 120 for row in rows)
    by_language = Counter(row.language_code for row in rows)
    return {
        "rows": len(rows), "by_language": dict(by_language),
        "with_vi_translation": sum(1 for row in rows if row.translations),
        "approx_table_mb_before_indexes": round(size / 1e6, 1),
    }
