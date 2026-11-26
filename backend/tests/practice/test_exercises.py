"""Every exercise type: the server builds it without its answer, and grades the learner's input against the card."""
import pytest

from app.modules.practice.domain.exercises import (
    BLANK,
    ExerciseUnavailable,
    generate,
    generate_with_fallback,
    grade,
    grade_pronunciation,
)
from tests.practice.fakes import MEANING_POOL, WORD_POOL, word

POOLS = {"meaning_pool": MEANING_POOL, "word_pool": WORD_POOL}
LEAVE = word("leave", meaning="rời đi", sentence="I have to leave now.")
NIHAO = word("你好", "zh", meaning="xin chào", reading="nǐ hǎo", sentence="他说你好。")


def build(kind, card=LEAVE):
    return generate(kind, card, seed="s", **POOLS)


def test_flashcard_shows_the_word_and_is_graded_by_the_learners_own_rating():
    exercise = build("flashcard")
    assert exercise.prompt["text"] == "leave" and exercise.prompt["meaning"] == "rời đi"
    assert grade("flashcard", LEAVE, {"rating": "good"}).outcome == "correct"
    assert grade("flashcard", LEAVE, {"rating": "hard"}).outcome == "partial"
    assert grade("flashcard", LEAVE, {"rating": "again"}).outcome == "incorrect"


def test_choice_offers_the_meaning_among_other_words_meanings_and_grades_the_chosen_text():
    exercise = build("choice")
    options = exercise.prompt["options"]
    assert "rời đi" in options and len(options) == 3 and len(set(options)) == 3
    assert exercise.prompt["sentence"] == "I have to leave now."
    assert build("choice").prompt == exercise.prompt  # the same order every time for the same seed
    assert grade("choice", LEAVE, {"option": "rời đi"}).correct is True
    assert grade("choice", LEAVE, {"option": next(o for o in options if o != "rời đi")}).correct is False
    assert grade("choice", LEAVE, {"option": "rời đi", "dont_know": True}).correct is False


def test_listening_hides_the_word_and_grades_the_chosen_word():
    exercise = build("listening")
    assert "leave" in exercise.prompt["options"] and len(exercise.prompt["options"]) == 4
    assert "text" not in exercise.prompt and "meaning" not in exercise.prompt
    assert grade("listening", LEAVE, {"option": "Leave"}).correct is True
    assert grade("listening", LEAVE, {"option": "apple"}).correct is False


def test_cloze_blanks_the_one_occurrence_from_the_video_sentence_and_grades_typed_text():
    exercise = build("cloze")
    assert exercise.prompt["sentence"] == f"I have to {BLANK} now."
    assert exercise.prompt["source"]["origin"] == "video" and "leave" not in exercise.prompt["source"]["text"]
    assert grade("cloze", LEAVE, {"text": "  LEAVE "}).correct is True
    assert grade("cloze", LEAVE, {"text": "live"}).correct is False
    zh = generate("cloze", NIHAO, seed="s", **POOLS)
    assert zh.prompt["sentence"] == f"他说{BLANK}。"
    assert grade("cloze", NIHAO, {"text": "你 好"}).correct is True


def test_cloze_is_not_built_when_the_word_is_missing_or_appears_twice():
    with pytest.raises(ExerciseUnavailable):
        build("cloze", word("leave", meaning="rời đi", sentence="Leave it, leave it."))
    with pytest.raises(ExerciseUnavailable):
        build("cloze", word("leave", meaning="rời đi"))


def test_pronunciation_is_graded_by_azures_band():
    assert build("pronunciation").prompt["text"] == "leave"
    assert grade_pronunciation(LEAVE, band="excellent", score=93).outcome == "correct"
    assert grade_pronunciation(LEAVE, band="fair", score=61).outcome == "partial"
    assert grade_pronunciation(LEAVE, band="retry", score=30).correct is False


def test_writing_is_by_stroke_for_han_characters_and_unavailable_for_latin_script():
    strokes = generate("writing", NIHAO, seed="s", **POOLS)
    assert strokes.prompt["script"] == "strokes" and strokes.prompt["characters"] == "你好"
    assert grade("writing", NIHAO, {"text": "你好", "mistakes": 3}).detail["mistakes"] == 3
    with pytest.raises(ExerciseUnavailable):
        build("writing")
    with pytest.raises(ExerciseUnavailable):
        grade("writing", LEAVE, {"text": "Leave"})


def test_an_exercise_that_cannot_be_built_falls_back_to_choice_then_flashcard():
    bare = word("leave")  # no meaning, no sentence
    assert generate_with_fallback("cloze", bare, seed="s", **POOLS).type == "flashcard"
    assert generate_with_fallback("cloze", word("leave", meaning="rời đi"), seed="s", **POOLS).type == "choice"


def test_match_pairs_a_word_with_its_meaning_and_grades_the_meaning_chosen_for_it():
    exercise = build("match")
    assert exercise.prompt == {"text": "leave", "reading": None, "meaning": "rời đi"}
    assert grade("match", LEAVE, {"option": "rời đi"}).correct is True
    assert grade("match", LEAVE, {"option": "quyển sách"}).correct is False
    with pytest.raises(ExerciseUnavailable):
        build("match", word("leave"))


def test_order_shuffles_the_sentence_or_the_characters_and_grades_the_order():
    exercise = build("order")
    assert exercise.prompt["kind"] == "sentence"
    assert sorted(exercise.prompt["parts"]) == sorted(["I", "have", "to", "leave", "now"])
    assert exercise.prompt["parts"] != ["I", "have", "to", "leave", "now"]
    assert grade("order", LEAVE, {"text": "I have to leave now"}).correct is True
    assert grade("order", LEAVE, {"text": "I have leave to now"}).correct is False
    assert grade("order", LEAVE, {"text": "I have to leave now"}).expected == "I have to leave now"
    chinese = build("order", NIHAO)
    assert chinese.prompt["kind"] == "sentence" and sorted(chinese.prompt["parts"]) == sorted("他说你好")
    assert grade("order", NIHAO, {"text": "他说你好"}).correct is True
    characters = build("order", word("银行", "zh", meaning="ngân hàng"))
    assert characters.prompt["kind"] == "characters" and characters.prompt["parts"] == ["行", "银"]
    with pytest.raises(ExerciseUnavailable):
        build("order", word("leave", meaning="rời đi"))  # no sentence, and English letters are not ordered
