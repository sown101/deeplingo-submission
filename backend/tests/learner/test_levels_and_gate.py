"""Level labels, the out-of-level warning and compatibility settings (L1a)."""
from datetime import UTC, datetime

import pytest

from app.modules.learner.domain.levels import (
    declarable_levels,
    is_above_level,
    level_rank,
    normalize_level,
    scale_for_language,
)
from app.modules.learner.domain.word_targets import (
    local_day_start,
    resolve_timezone,
    validate_daily_new_limit,
)


def test_each_language_has_its_own_scale_and_never_the_other():
    assert (scale_for_language("en"), scale_for_language("EN-us"), scale_for_language("zh"), scale_for_language("vi")) == (
        "CEFR", "CEFR", "HSK", None)
    assert normalize_level("en", "b1+") == "B1+"
    assert normalize_level("zh", "hsk 4") == "HSK4"
    assert normalize_level("zh", "B1") is None
    assert normalize_level("en", "HSK3") is None
    assert level_rank("en", "A2") < level_rank("en", "A2+") < level_rank("en", "B1")


def test_declared_levels_are_the_languages_declarable_labels_only():
    assert "A2+" in declarable_levels("en") and "C2" not in declarable_levels("en")
    assert "HSK3" in declarable_levels("zh") and "HSK7" not in declarable_levels("zh")
    assert declarable_levels("fr") == ()


@pytest.mark.parametrize("language, word, declared, expected", [
    ("en", "B1", "A2", False),   # one band above is fine
    ("en", "B2", "A2", True),    # two bands above warns
    ("en", "B2", "A2+", True),
    ("en", "B1", "A2+", False),
    ("en", "A1", "B2", False),   # easier words never warn
    ("en", "C1", "B1", True),
    ("en", None, "A2", False),   # an unclassified word never warns
    ("en", "B2", None, False),   # an undeclared level never warns
    ("zh", "HSK4", "HSK3", False),
    ("zh", "HSK5", "HSK3", True),
    ("zh", "HSK7", "HSK5", True),
    ("zh", "B2", "HSK3", False),  # scales are never mixed
])
def test_out_of_level_warns_only_for_a_known_word_more_than_one_band_above(language, word, declared, expected):
    assert is_above_level(language, word, declared) is expected


def test_the_daily_limit_is_between_one_and_fifty():
    assert validate_daily_new_limit(10) == 10
    for bad in (0, 51, -3):
        with pytest.raises(ValueError):
            validate_daily_new_limit(bad)


def test_the_local_day_starts_at_local_midnight_in_the_learners_timezone():
    now = datetime(2026, 10, 25, 20, 30, tzinfo=UTC)  # 03:30 on 26 Oct in Ho Chi Minh City
    assert local_day_start(now, "Asia/Ho_Chi_Minh") == datetime(2026, 10, 25, 17, 0, tzinfo=UTC)
    assert local_day_start(now, "UTC") == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    assert local_day_start(now, "Not/AZone") == datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    assert resolve_timezone(None).key == "UTC"
