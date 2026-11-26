"""Whole conversations with simulated learners (harness plan phase 7), scripted: no live AI in normal tests.

A well-behaved fake agent passes every rule for every persona; agents that break one rule are caught by it.
"""
import pytest

from app.modules.learning.application.agent.dialogues import PERSONAS, run_dialogue, score_dialogue, stalled
from tests.learning.test_companion import FakeModel, Turn

OPENING = Turn("Hello! What would you like to talk about?", "Xin chào! Bạn muốn nói về gì?")


def say(reply, support="Bản dịch.", **calls):
    return Turn(reply, support, [(name, args) for name, args in calls.items()])


HINT = {"show_hint": {"question": "Bạn mua gì ở chợ?", "words": ["market"]}}

GOOD = {
    "a1_beginner_en": [OPENING, say("Nice! When do you drink coffee?"), say("Every morning! Who makes it?"),
                       say("Your mother makes coffee. How do you like it?"), say("With milk, nice. Do you like tea?")],
    "hesitant_en": [OPENING, say("Take your time. Where do you go on Sunday?", **HINT),
                    say("You went to the market! What did you buy?"),
                    say("That is okay. Did you buy fruit?", **HINT), say("Apples and bread. Are they for breakfast?")],
    "mixes_vietnamese_en": [OPENING, say("Going to the market on Sunday is fun! Why do you like it?"),
                            say("Vegetables are fresh there. What do you buy?"),
                            say("Fish and vegetables! Do you cook them?"), say("Great. What do you cook?")],
    "b1_en": [OPENING, say("Da Lat sounds lovely. What was the weather like?"),
              say("Cold mornings and amazing views. Where did you stay?"),
              say("I have only read about it. What did you like most about the homestay?"),
              say("The rainy season is beautiful there. What would you do differently?")],
    "goal_en": [OPENING, say("A hotel job, great goal! Which city?", remember={
                    "kind": "goal", "text": "Học tiếng Anh để làm ở khách sạn năm sau."}),
                say("Da Nang is lovely. What will you do at work?"), say("You will talk to guests. What do you say first?"),
                say("It is normal to be nervous. Shall we practise a greeting?")],
    "hsk1_zh": [Turn("你好！你想说什么？", "Xin chào! Bạn muốn nói gì?"), say("你喜欢喝什么茶？", "Bạn thích uống trà gì?"), say("绿茶很好。你每天喝吗？", "Bạn uống mỗi ngày không?"),
                say("你早上喝吗？", "Buổi sáng à?"), say("好。你喜欢咖啡吗？", "Bạn thích cà phê không?")],
}


@pytest.mark.parametrize("persona", PERSONAS, ids=[persona.id for persona in PERSONAS])
def test_a_well_behaved_agent_keeps_every_rule_with_every_persona(persona):
    result = run_dialogue(FakeModel(GOOD[persona.id]), persona)
    assert result.ok, (result.checks, result.error)
    assert len(result.turns) == len(persona.script)


def persona(name):
    return next(item for item in PERSONAS if item.id == name)


def test_no_help_after_a_stall_is_caught():
    script = [OPENING, say("Where do you go on Sunday?"), say("What did you buy?"), say("Did you buy fruit?"),
              say("Are they for breakfast?")]
    result = run_dialogue(FakeModel(script), persona("hesitant_en"))
    assert result.checks["help_after_stall"] is False and not result.ok


def test_an_agent_that_stops_asking_is_caught():
    script = [OPENING, say("Coffee is nice."), say("Mornings are good."), say("Mothers are kind."),
              say("Milk is good.")]
    assert run_dialogue(FakeModel(script), persona("a1_beginner_en")).checks["keeps_learner_talking"] is False


def test_a_goal_that_is_not_remembered_is_caught():
    script = [OPENING, *GOOD["goal_en"][1:]]
    script[1] = say("A hotel job, great goal! Which city?")
    assert run_dialogue(FakeModel(script), persona("goal_en")).checks["goal_remembered"] is False


def test_the_rules_read_what_the_learner_saw():
    b1 = persona("b1_en")
    record = [{"said": "I went hiking.", "reply": "Mình hiểu rồi. Bạn đi đâu?", "support": "", "shown": []}]
    assert score_dialogue(b1, record)["language_policy"] is False  # from B1 the reply stays in English
    record = [{"said": "I went hiking.", "reply": "Great job, 9 out of 10! Where?", "support": "", "shown": []}]
    assert score_dialogue(b1, record)["no_score_claim"] is False
    assert stalled("Um... uh...", "en") and stalled("I don't know how to say it.", "en")
    assert not stalled("I went to the market.", "en")


def test_the_same_reply_twice_in_a_row_is_caught():
    record = [{"said": "I drink coffee at seven.", "reply": "What time do you drink coffee?", "support": "", "shown": []},
              {"said": "At seven.", "reply": "What time do you  drink coffee?", "support": "", "shown": []}]
    assert score_dialogue(persona("a1_beginner_en"), record)["no_repeated_reply"] is False


def test_a_chinese_question_without_a_question_mark_still_asks():
    from app.modules.learning.application.agent.dialogues import asks
    assert asks("你今天喝茶了吗") and asks("你呢。") and asks("Where?") and not asks("绿茶很好喝！")
