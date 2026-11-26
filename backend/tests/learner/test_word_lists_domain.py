"""L1b: reading the pasted import text and naming lists."""
from uuid import uuid4

import pytest

from app.modules.learner.domain.word_lists import (
    MAX_BATCH_LINES,
    MAX_GLOSS_CHARS,
    MAX_WORD_CHARS,
    SenseCandidate,
    parse_import_batch,
    validate_list_name,
)


def words(text, **kwargs):
    return [(line.word, line.gloss) for line in parse_import_batch(text, **kwargs).lines]


def test_one_word_per_line_with_an_optional_meaning_after_a_tab_comma_or_semicolon():
    text = "rely on\ngive up\tto stop trying\nput off, to delay\ntake off ; to leave the ground"
    assert words(text) == [("rely on", None), ("give up", "to stop trying"), ("put off", "to delay"),
                           ("take off", "to leave the ground")]


def test_quotes_spaces_invisible_characters_and_blank_or_comment_lines_are_ignored():
    text = '﻿"rely on"  \n\n# my travel words\n  “airport” ​\n'
    parsed = parse_import_batch(text)
    assert [line.word for line in parsed.lines] == ["rely on", "airport"]
    assert parsed.blank == 2


def test_the_same_word_twice_is_read_once_ignoring_case():
    parsed = parse_import_batch("Airport\nairport\nAIRPORT, a place\nluggage")
    assert [line.word for line in parsed.lines] == ["Airport", "luggage"]
    assert parsed.duplicates == 2


def test_a_full_width_comma_is_part_of_a_chinese_phrase_not_a_separator():
    parsed = parse_import_batch("你好，世界\n机场, airport")
    assert [(line.word, line.gloss) for line in parsed.lines] == [("你好，世界", None), ("机场", "airport")]


def test_a_word_that_is_too_long_is_counted_not_read_and_a_long_meaning_is_cut():
    parsed = parse_import_batch(f"{'x' * (MAX_WORD_CHARS + 1)}\nok, {'m' * (MAX_GLOSS_CHARS + 50)}")
    assert parsed.too_long == 1
    assert [line.word for line in parsed.lines] == ["ok"]
    assert len(parsed.lines[0].gloss) == MAX_GLOSS_CHARS


def test_only_the_first_lines_of_a_batch_are_read_and_the_rest_are_counted():
    text = "\n".join(f"word{n}" for n in range(MAX_BATCH_LINES + 7))
    parsed = parse_import_batch(text)
    assert len(parsed.lines) == MAX_BATCH_LINES and parsed.over_limit == 7
    assert len(parse_import_batch(text, max_lines=3).lines) == 3


def test_an_empty_text_reads_nothing():
    assert parse_import_batch("").lines == [] and parse_import_batch(None).lines == []


def test_a_list_name_is_trimmed_and_limited_to_sixty_characters():
    assert validate_list_name("  IELTS   Part 2 ") == "IELTS Part 2"
    for bad in ("", "   ", "x" * 61):
        with pytest.raises(ValueError):
            validate_list_name(bad)


def test_a_sense_candidate_survives_storage_as_json():
    candidate = SenseCandidate(entry_id=uuid4(), sense_id="enwikt:bank1", headword="bank", text="A river side.",
                               part_of_speech="noun")
    assert SenseCandidate.from_json(candidate.as_json()) == candidate
