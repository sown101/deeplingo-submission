"""Meaning choices for the practice exercises: usable meanings, plain dictionary examples and distractors.
Lexical safeguards, not a semantic quality certification."""
import pytest

from app.modules.practice.domain import meaning_choices as mc

POOL = [("give up", "To stop trying."), ("run", "To move quickly on foot."), ("eat", "To consume food."),
        ("put off", "To postpone."), ("sleep", "To rest with the eyes closed.")]
TEMPEST = ("Knowing I lou'd my bookes, he furnishd me / From mine owne Library, with volumes, that / "
           "I prize aboue my Dukedome.")


def test_distractors_never_use_the_same_headword_or_the_answer_and_keep_a_stable_order():
    first = mc.pick_meaning_distractors(correct="To delay.", headword="put off",
                                        pool=[*POOL, ("x", "to delay")], order_seed="a")
    again = mc.pick_meaning_distractors(correct="To delay.", headword="put off", pool=list(reversed(POOL)),
                                        order_seed="a")
    assert first == again and len(first) == 2
    assert "To postpone." not in first and all(option.casefold() != "to delay" for option in first)
    with pytest.raises(mc.QuickReviewQuestionUnavailable):
        mc.pick_meaning_distractors(correct="To delay.", headword="put off", pool=[("put off", "x")], order_seed="a")


@pytest.mark.parametrize("correct,ambiguous", [
    ("phát hiện, tìm hiểu thông tin mới", "phơi bày, vạch trần, phát hiện"),
    ("发现；了解新信息", "揭露；发现；揭开"),
])
def test_shared_gloss_alternative_is_not_hidden_by_other_alternatives(correct, ambiguous):
    pool = [("other", ambiguous), ("eat", "ăn cơm")]
    with pytest.raises(mc.QuickReviewQuestionUnavailable, match="not_enough_distractors"):
        mc.pick_meaning_distractors(correct=correct, headword="target", pool=pool, order_seed="quality")


def test_lexical_gate_does_not_claim_to_detect_nonlexical_synonyms():
    # The real find out / uncover pair: retained for editorial review, not auto-approved.
    assert not mc._too_close("khám phá, tìm ra thông tin", "phơi bày, vạch trần, phát hiện")


def test_wrong_options_are_never_close_to_the_answer_or_to_each_other():
    pool = [("a", "hoãn lại một chút", "verb"), ("b", "Hoãn lại", "verb"), ("c", "hoãn lại cuộc họp", "verb"),
            ("d", "chạy nhanh", "verb"), ("e", "nhanh chạy", "verb"), ("f", "ăn sáng", "verb"),
            ("put off", "để sau", "verb")]
    chosen = mc.pick_meaning_distractors(correct="hoãn lại", headword="put off", pool=pool, order_seed="s",
                                         part_of_speech="verb")
    assert len(chosen) == 2 and set(chosen) <= {"chạy nhanh", "nhanh chạy", "ăn sáng"}
    assert not {"chạy nhanh", "nhanh chạy"} <= set(chosen)  # the same words in another order: only one
    with pytest.raises(mc.QuickReviewQuestionUnavailable):
        mc.pick_meaning_distractors(correct="hoãn lại", headword="put off", pool=pool[:3], order_seed="s")


def test_the_same_part_of_speech_comes_first():
    pool = [("x", "ngôi nhà", "noun"), ("y", "con mèo", "noun"), ("z", "chạy", "verb"), ("w", "ăn", "verb")]
    assert set(mc.pick_meaning_distractors(correct="hoãn lại", headword="put off", pool=pool, order_seed="s",
                                           part_of_speech="verb")) == {"chạy", "ăn"}


def test_old_quotations_are_not_plain_examples():
    assert not mc.plain_dictionary_example(TEMPEST)
    assert not mc.plain_dictionary_example("Thou art my friend.")
    assert not mc.plain_dictionary_example("He furniſhd me.")
    assert mc.plain_dictionary_example("I read a book every night.")


def test_an_untranslated_english_word_is_not_a_vietnamese_option():
    assert not mc.usable_distractor_meaning("chaff", "vi")
    assert mc.usable_distractor_meaning("Bánh mì mềm", "vi")
    assert mc.usable_distractor_meaning("chaff", "en")
