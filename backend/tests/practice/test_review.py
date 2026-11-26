"""The review engine: decks per language, one answer path, FSRS at most once per card per pass, one log row."""
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from app.modules.practice.application.review import PracticeError, ReviewAnswer
from app.modules.review.domain.grades import FAST_ANSWER_MS, grade_for_self_rating
from app.modules.review.domain.models import ReviewGrade
from tests.practice.fakes import OTHER, USER, make_review, word

EN = word("leave", meaning="rời đi", sentence="I have to leave now.")
EN2 = word("table", meaning="cái bàn", sentence="The book is on the table.")
ZH = word("你好", "zh", meaning="xin chào", sentence="他说你好。")


def answer(card, kind="choice", *, event=None, pass_id="pass-1", **answer_fields):
    fields = {"choice": {"option": card.meaning}, "flashcard": {"rating": "good"}, "cloze": {"text": card.text},
              "writing": {"text": card.text}, "listening": {"option": card.text}, "match": {"option": card.meaning},
              "order": {"text": card.sentence.text if card.sentence else card.text}}[kind]
    return ReviewAnswer(user_id=USER, concept_id=card.concept_id, language_code=card.language_code,
                        exercise_type=kind, client_event_id=event or str(uuid4()), pass_id=pass_id,
                        answer={**fields, **answer_fields})


def test_decks_are_per_language_and_a_deck_never_holds_another_languages_card():
    env = make_review([EN, EN2, ZH])
    assert [(deck["language_code"], deck["new_count"]) for deck in env.service.decks(USER)] == [("en", 2), ("zh", 1)]
    english = env.service.due(USER, "en", mode="choice")
    assert {card["concept_id"] for card in english["cards"]} == {EN.concept_id, EN2.concept_id}
    chinese = env.service.due(USER, "zh", mode="choice")
    assert [card["concept_id"] for card in chinese["cards"]] == [ZH.concept_id]
    # Asking the English deck for the Chinese word gives nothing.
    assert env.service.due(USER, "en", concept_ids=[ZH.concept_id])["cards"] == []


def test_due_cards_come_before_new_cards_and_carry_no_answer_key():
    env = make_review([EN, EN2])
    env.service.answer(answer(EN, pass_id="earlier"))
    env.clock.advance(days=30)
    cards = env.service.due(USER, "en", mode="choice")["cards"]
    assert [card["concept_id"] for card in cards] == [EN.concept_id, EN2.concept_id]
    assert [card["is_new"] for card in cards] == [False, True]
    assert all("expected" not in str(card["exercise"]) for card in cards)


def test_mixed_mode_cycles_through_the_exercise_types():
    cards = [word(f"w{index}", meaning=f"nghĩa số {index}", sentence=f"Say w{index} here.") for index in range(5)]
    env = make_review(cards)
    types = [card["exercise"]["type"] for card in env.service.due(USER, "en")["cards"]]
    assert sorted(types) == sorted(["choice", "listening", "cloze", "flashcard", "choice"])


@pytest.mark.parametrize("kind", ["flashcard", "choice", "listening", "cloze", "match", "order"])
def test_every_type_grades_schedules_once_and_logs_exactly_one_row(kind):
    env = make_review([EN])
    result = env.service.answer(answer(EN, kind))
    assert (result["correct"], result["scheduled"], result["grade"]) == (True, True, "good")
    assert result["next_review_at"] is not None
    rows = env.log.of(kind)
    assert len(rows) == 1 and len(env.store.events) == 1
    assert (rows[0].item_id, rows[0].source_type, rows[0].source_id) == (str(EN.concept_id), "review_deck", "pass-1")


def test_a_card_changes_schedule_at_most_once_per_pass():
    env = make_review([EN])
    first = env.service.answer(answer(EN, "choice"))
    second = env.service.answer(answer(EN, "cloze", text="wrong"))
    assert first["scheduled"] is True and second["scheduled"] is False
    assert len(env.store.events) == 1 and env.store.states[(USER, EN.concept_id)]["version"] == 1
    assert [row.outcome for row in env.log.entries] == ["correct", "incorrect"]  # both results are kept
    third = env.service.answer(answer(EN, "choice", pass_id="pass-2"))
    assert third["scheduled"] is True and len(env.store.events) == 2


def test_a_retried_answer_is_stored_once_and_returns_the_stored_result():
    env = make_review([EN])
    request = answer(EN, "choice", event="evt-1")
    first = env.service.answer(request)
    again = env.service.answer(request)
    assert again["duplicate"] is True and first["duplicate"] is False
    assert (again["correct"], again["grade"], again["scheduled"]) == (True, "good", True)
    assert len(env.log.entries) == 1 and len(env.store.events) == 1


def test_a_concurrent_change_is_recomputed_on_the_fresh_state():
    env = make_review([EN])
    env.store.conflicts_left = 2
    assert env.service.answer(answer(EN))["scheduled"] is True
    env.store.conflicts_left = 5
    with pytest.raises(PracticeError) as error:
        env.service.answer(answer(EN, pass_id="p2"))
    assert error.value.code == "review_changed"


def test_grades_follow_the_one_mapping():
    env = make_review([EN])
    wrong = env.service.answer(answer(EN, "choice", option="cái bàn"))
    assert (wrong["correct"], wrong["grade"], wrong["outcome"]) == (False, "again", "incorrect")
    hinted = env.service.answer(replace(answer(EN, "choice", pass_id="p2"), hint_used=True))
    assert hinted["grade"] == "hard"
    fast = replace(answer(EN, "choice", pass_id="p3"), response_ms=FAST_ANSWER_MS - 1)
    assert env.service.answer(fast)["grade"] == "good"  # fast, but the answer before it was not fast
    faster = replace(answer(EN, "choice", pass_id="p4"), response_ms=900)
    assert env.service.answer(faster)["grade"] == "easy"  # fast again in a row
    flash = env.service.answer(answer(EN, "flashcard", pass_id="p5", rating="hard"))
    assert (flash["grade"], flash["outcome"]) == ("hard", "partial")
    assert grade_for_self_rating("remembered") is ReviewGrade.GOOD


def test_a_word_that_is_not_the_learners_or_is_known_is_refused_and_logs_nothing():
    env = make_review([EN], save=False)
    with pytest.raises(PracticeError) as error:
        env.service.answer(answer(EN))
    assert error.value.code == "word_not_in_review" and env.log.entries == []
    env.store.save(OTHER, EN)
    with pytest.raises(PracticeError):
        env.service.answer(answer(EN))
    env.store.save(USER, EN, eligible=False)
    with pytest.raises(PracticeError):
        env.service.answer(answer(EN))
    assert env.log.entries == [] and env.store.events == []


def test_a_correct_answer_closes_the_agents_word_review_request():
    env = make_review([EN])
    env.activity.create_study_request(USER, language_code="en", kind="word_review", item_id=str(EN.concept_id),
                                      reason=None, created_by="agent")
    env.service.answer(answer(EN, option="cái bàn"))
    assert env.requests.rows[0].status == "open"
    env.service.answer(answer(EN, pass_id="p2"))
    assert env.requests.rows[0].status == "done"


@pytest.mark.parametrize("answer_input", [{}, {"rating": None}, {"rating": "perfect"}])
def test_a_flashcard_answer_without_a_known_rating_is_refused_and_logs_nothing(answer_input):
    env = make_review([EN])
    with pytest.raises(PracticeError) as error:
        env.service.answer(ReviewAnswer(user_id=USER, concept_id=EN.concept_id, language_code="en",
                                        exercise_type="flashcard", client_event_id="evt-r", answer=answer_input))
    assert (error.value.status_code, error.value.code) == (422, "flashcard_rating_required")
    assert env.log.of("flashcard") == [] and env.store.events == []


def test_the_flutter_memory_rating_runs_as_a_flashcard_answer():
    env = make_review([ZH])
    due = env.service.rate_memory(USER, ZH.concept_id, "not_yet", "evt-9")
    assert due is not None and env.store.events[0]["rating"] == 1
    assert env.service.rate_memory(USER, ZH.concept_id, "not_yet", "evt-9") == due  # a retry changes nothing
    row = env.log.of("flashcard")
    assert len(row) == 1 and (row[0].outcome, row[0].language_code) == ("incorrect", "zh")
    with pytest.raises(PracticeError):
        env.service.rate_memory(USER, uuid4(), "unsure", "evt-10")


def test_pronunciation_is_scored_by_azure_logged_with_its_whole_result_and_never_moves_the_schedule():
    env = make_review([EN])
    request = replace(answer(EN), exercise_type="pronunciation", answer={})
    assessment = {"band": "good", "recognized_text": "Leave.", "scores": {"pronunciation": 84.4, "accuracy": 80.0,
                  "fluency": 90.0, "completeness": 100.0, "prosody": 75.0},
                  "words": [{"word": "leave", "accuracy": 80.0, "error_type": "none",
                             "phonemes": [{"phoneme": "l", "accuracy": 95.0}, {"phoneme": "iː", "accuracy": 60.0}]}]}
    result = env.service.answer_pronunciation(request, band="good", score=84.4, assessment=assessment)
    assert result["correct"] is True and result["scheduled"] is False
    assert env.store.states == {} and env.store.events == []
    row = env.log.of("pronunciation")[0]
    assert (row.score, row.detail["band"]) == (84.4, "good")
    assert row.detail["assessment"]["words"][0]["phonemes"][1] == {"phoneme": "iː", "accuracy": 60.0}
    assert "recognized_text" not in row.detail["assessment"]
    latest = env.service.latest_pronunciation(USER, EN.concept_id)
    assert latest["score"] == 84.4 and latest["detail"]["assessment"]["scores"]["prosody"] == 75.0


def test_writing_is_graded_and_logged_but_never_moves_the_schedule():
    """Owner decision 2026-11-14: only Review (Ôn tập) and Flashcard change FSRS; writing is practice."""
    env = make_review([ZH])
    result = env.service.answer(answer(ZH, "writing"))
    assert (result["correct"], result["scheduled"]) == (True, False)
    assert env.store.states == {} and env.store.events == []
    assert len(env.log.of("writing")) == 1
    # A later scheduled answer in the same pass still moves the card once.
    assert env.service.answer(answer(ZH, "choice"))["scheduled"] is True


def test_writing_a_latin_script_word_is_unavailable():
    env = make_review([EN])
    with pytest.raises(PracticeError) as error:
        env.service.answer(answer(EN, "writing"))
    assert error.value.code == "exercise_unavailable" and env.log.of("writing") == []


def test_review_settings_take_the_chosen_types_in_turn_and_never_another_type():
    cards = [word(f"w{index}", meaning=f"nghĩa số {index}", sentence=f"Please say w{index} here.")
             for index in range(4)]
    env = make_review(cards)
    types = [card["exercise"]["type"] for card in env.service.due(USER, "en", types=["choice", "order"])["cards"]]
    assert sorted(types) == ["choice", "choice", "order", "order"]
    # A word with no meaning cannot be matched and has no sentence to order: it is left out, not turned into a card.
    env = make_review([word("bare"), *cards[:1]])
    assert [card["exercise"]["type"] for card in env.service.due(USER, "en", types=["match", "order"])["cards"]]         in (["match"], ["order"])
    with pytest.raises(PracticeError):
        env.service.due(USER, "en", types=["guessing"])


def test_the_clock_moves_cards_back_into_the_deck():
    env = make_review([EN])
    env.service.answer(answer(EN))
    assert env.service.decks(USER)[0]["due_count"] == 0
    env.clock.advance(days=60)
    assert env.service.decks(USER)[0]["due_count"] == 1
    assert timedelta(days=60)
