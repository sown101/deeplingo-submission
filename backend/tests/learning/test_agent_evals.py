"""The agent's fixed eval scenarios with a scripted fake model (TARGET_DESIGN §7): no live AI in normal tests.

The fake model plays a well-behaved agent on the real loop; what is measured is what the server decides around it:
the tool it lets the agent call and on whose data, the help it lets the agent show unasked, the language policy of
the learner's level, the grammar_redo it creates for a corrected approved point, that nothing of another learner
reaches the prompt or the answer, and that each turn is logged. The same scenarios run against the real model in
`scripts/agent/eval_live.py`.
"""
import pytest

from app.modules.learning.application.agent.evals import (
    AIRPORT_ID, OTHER_SECRET, OTHER_WORD_ID, PAST_SIMPLE, SCENARIOS, run_scenario)
from app.modules.learning.application.agent.prompts import OPEN_START_CUE, START_CUE
from app.platform.llm.port import ChatReply, ToolCall
from tests.learning.test_companion import FakeModel, Turn, turn_output

OPENING = Turn("Hello! What would you like to do today?", "Xin chào! Hôm nay bạn muốn làm gì?")


def say(reply, support="Bản dịch.", **calls):
    return Turn(reply, support, [(name, args) for name, args in calls.items()])


def tool(name, **args):
    return ChatReply(None, (ToolCall("t1", name, args),))


SCRIPTS = {
    "a1_topic_en": [OPENING, say("Nice! Do you drink coffee every day?")],
    "hsk1_topic_zh": [OPENING, say("你喜欢喝什么茶？", "Bạn thích uống trà gì?")],
    "hesitation": [OPENING, say("Take your time. What do you drink in the morning?", show_hint={
        "question": "Bạn uống gì vào buổi sáng?", "words": ["coffee"]})],
    "cannot_say_it": [OPENING, say("That is okay. What do you like to eat?", show_hint={
        "question": "Bạn thích ăn gì?", "frame": "I like ___.", "frame_reason": "Nói điều bạn thích."})],
    "grammar_error": [OPENING, say(
        "Try again: Yesterday I went to the market.", show_correction={
            "quote": "I go", "suggestion": "I went", "note": "Thử lại: dùng quá khứ 'went'.",
            "grammar_point": PAST_SIMPLE})],
    "unnatural_sentence": [OPENING, say("Nice! What kind of coffee do you like?", show_natural={"options": [
        {"sentence": "I like to drink coffee.", "explanation": "Tự nhiên hơn khi nói về sở thích."}]})],
    "explains_in_vietnamese_a1": [OPENING, say(
        "Vì có 'yesterday' (hôm qua), động từ chuyển sang quá khứ: go thành went. Bạn thử nói lại nhé?", "",
        explain_grammar={"grammar_point": PAST_SIMPLE})],
    # The first answer slips into Vietnamese at B2: the loop sends it back and the agent answers in English.
    "english_only_b2": [OPENING, Turn("Được chứ, mình nói tiếng Việt nhé. Bạn thích gì?", ""),
                        say("Let me say it simply in English. What do you like to drink?")],
    "off_topic": [OPENING, say("Let's talk about you. What do you like to drink?")],
    "roleplay": [Turn("Good evening! How can I help you?"), say("Let me check. What is your name, please?")],
    "yesterday": [OPENING, tool("get_recent_activity", days=1),
                  say("Yesterday you reviewed airport and did a dictation. Shall we use airport now?")],
    "remembers_goal": [OPENING, say("A hotel! Great goal. What do you do now?", remember={
        "kind": "goal", "text": "Học tiếng Anh để làm việc ở khách sạn vào năm sau."})],
    "uses_memory": [OPENING, say("Let's practise hotel talk, since you want to work in a hotel. How do you greet a guest?")],
    # The agent reads the due words, then names their ids (and, wrongly, one that is not the learner's own).
    "review_now": [OPENING, tool("get_due_cards"),
                   say("Your review is ready. Tap the button when you want to start.", open_review={
                       "concept_ids": [AIRPORT_ID, OTHER_WORD_ID]})],
    "add_review_today": [OPENING, say("Done, I added a review to your tasks for today.", edit_today={
        "change": "add", "kind": "review"})],
}


def scenario_named(name):
    return next(item for item in SCENARIOS if item.id == name)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario.id for scenario in SCENARIOS])
def test_scenario_passes_with_a_well_behaved_fake_model(scenario):
    model = FakeModel(SCRIPTS[scenario.id])
    result = run_scenario(model, scenario)
    assert result.ok, result.checks
    assert model.queue == []  # the loop asked exactly as often as the scenario expects
    assert all(OTHER_SECRET not in prompt for prompt in model.prompts)
    assert result.latency_ms >= 0


def test_the_agent_opens_by_asking_what_the_learner_wants_and_picks_no_topic():
    """Home without a chosen topic: the opening cue forbids picking one and the view offers the choices."""
    for scenario in SCENARIOS:
        model = FakeModel(SCRIPTS[scenario.id])
        result = run_scenario(model, scenario)
        assert result.checks["opening_choices"]
        opening = model.calls[0][0][-1]["content"]
        assert opening == (OPEN_START_CUE if scenario.scenario_id is None else START_CUE)
        assert model.calls[0][1] == []  # a greeting needs no tools


def test_the_scenario_set_covers_the_required_cases():
    assert {scenario.id for scenario in SCENARIOS} == {
        "a1_topic_en", "hsk1_topic_zh", "hesitation", "cannot_say_it", "grammar_error", "unnatural_sentence",
        "explains_in_vietnamese_a1", "english_only_b2", "off_topic", "roleplay", "yesterday", "remembers_goal",
        "uses_memory", "review_now", "add_review_today"}


def test_what_did_i_study_yesterday_reads_the_learners_own_log_and_answers_from_it():
    model = FakeModel(SCRIPTS["yesterday"])
    result = run_scenario(model, scenario_named("yesterday"))
    assert result.tools == ["get_recent_activity"]
    # The tool result reached the model as data, with the learner's own word and none of anyone else's.
    result_message = next(m for m in reversed(model.calls[-1][0]) if m["role"] == "tool")
    assert "airport" in result_message["content"] and "boarding pass" in result_message["content"]


def test_help_is_given_unasked_after_a_wrong_or_an_unnatural_sentence():
    wrong = run_scenario(FakeModel(SCRIPTS["grammar_error"]), scenario_named("grammar_error"))
    assert wrong.shown == ["correction"] and wrong.checks["grammar_redo"]
    unnatural = run_scenario(FakeModel(SCRIPTS["unnatural_sentence"]), scenario_named("unnatural_sentence"))
    assert unnatural.shown == ["natural"]
    # Nobody pressed a button: the learner's line is the only thing the agent was told, and the display tools are on offer.
    model = FakeModel(SCRIPTS["unnatural_sentence"])
    run_scenario(model, scenario_named("unnatural_sentence"))
    assert model.calls[1][0][-1] == {
        "role": "user", "content": "<learner_said>I have a hobby which is drinking coffee.</learner_said>"}
    assert {"show_natural", "show_correction", "show_hint", "explain_grammar"} <= set(model.calls[1][1])


def test_an_a1_learner_who_asks_in_vietnamese_gets_a_vietnamese_explanation_a_b2_learner_does_not():
    a1_model = FakeModel(SCRIPTS["explains_in_vietnamese_a1"])
    a1 = run_scenario(a1_model, scenario_named("explains_in_vietnamese_a1"))
    assert a1.ok and a1.shown == ["grammar"] and "quá khứ" in a1.reply
    assert "You may explain in Vietnamese" in a1_model.prompts[0]

    b2_model = FakeModel(SCRIPTS["english_only_b2"])
    b2 = run_scenario(b2_model, scenario_named("english_only_b2"))
    assert b2.ok and b2.reply.startswith("Let me say it simply in English")
    assert "speak only English" in b2_model.prompts[0] and "may explain in Vietnamese" not in b2_model.prompts[0]
    # The Vietnamese slip was sent back to the agent, never shown, and the session went on.
    assert len(b2_model.calls) == 3
    assert "only in the learning language" in b2_model.calls[-1][0][-1]["content"]


def test_hesitation_reaches_the_agent_as_an_event_and_the_help_is_the_agents_choice():
    for name in ("hesitation", "cannot_say_it"):
        model = FakeModel(SCRIPTS[name])
        result = run_scenario(model, scenario_named(name))
        assert result.shown == ["hint"] and result.ok
        event_message = next(m for m in model.calls[1][0] if "(Event:" in str(m.get("content")))
        assert "Choose how to help" in event_message["content"]
    # An agent that decides not to hint fails the live scenario, but never the turn: the server forces no step.
    quiet = run_scenario(FakeModel([OPENING, say("Take your time. What do you drink?")]), scenario_named("hesitation"))
    assert quiet.checks["turn"] and quiet.checks["help_shown"] is False


def test_a_wrong_or_missing_tool_choice_fails_the_scenario():
    result = run_scenario(FakeModel([OPENING, say("I do not know. What do you like?")]), scenario_named("yesterday"))
    assert result.ok is False and result.checks["tool"] is False


def test_a_correction_without_an_approved_point_creates_no_request_and_fails_the_grammar_scenario():
    script = [OPENING, turn_output(
        reply="Try again: Yesterday I went to the market.", correction={
            "quote": "I go", "suggestion": "I went", "note_support": "Thử lại.", "grammar_point": "en.made.up"})]
    result = run_scenario(FakeModel(script), scenario_named("grammar_error"))
    assert result.checks["grammar_redo"] is False


def test_a_lasting_goal_is_remembered_for_this_learner_only():
    model = FakeModel(SCRIPTS["remembers_goal"])
    result = run_scenario(model, scenario_named("remembers_goal"))
    assert result.ok and result.checks["memory_stored"] and result.checks["no_other_learner"]
    # Quiet: nothing about it is shown to the learner.
    assert result.shown == []


def test_a_remembered_goal_reaches_the_prompt_of_a_later_conversation_and_nobody_elses_does():
    model = FakeModel(SCRIPTS["uses_memory"])
    result = run_scenario(model, scenario_named("uses_memory"))
    assert result.ok and result.checks["memory_read"]
    assert all("Learning English to work in a hotel next year." in prompt for prompt in model.prompts)
    assert all(OTHER_SECRET not in prompt for prompt in model.prompts)
    # "The answer uses it" is a live-only check, like the yesterday scenario.
    assert "mentions" not in result.checks
    assert run_scenario(FakeModel([OPENING, say("Nice! What do you drink?")]), scenario_named("uses_memory"),
                        live=True).checks["mentions"] is False


def test_review_now_reads_the_due_cards_then_opens_a_review_of_only_the_learners_own_words():
    model = FakeModel(SCRIPTS["review_now"])
    result = run_scenario(model, scenario_named("review_now"))
    assert result.ok, result.checks
    assert result.tools == ["get_due_cards", "open_review"]
    # The ids reached the agent in the tool result, so it never has to invent one.
    due_message = next(m for m in model.calls[2][0] if m["role"] == "tool")
    assert AIRPORT_ID in due_message["content"]
    # The other learner's id was dropped by the server and the card holds exactly the learner's word.
    done_message = next(m for m in reversed(model.calls[-1][0]) if m["role"] == "tool")
    assert '"words": 1' in done_message["content"] and '"dropped": 1' in done_message["content"]


def test_add_a_review_to_my_tasks_today_calls_edit_today_and_shows_what_changed():
    model = FakeModel(SCRIPTS["add_review_today"])
    result = run_scenario(model, scenario_named("add_review_today"))
    assert result.ok, result.checks
    assert "edit_today" in {name for name in model.calls[1][1]}
    assert result.checks["action"] and result.checks["action_own_data"]


def test_an_action_card_nobody_asked_for_fails_the_scenario():
    unasked = [OPENING, say("Nice! Do you drink coffee every day?", edit_today={"change": "add", "kind": "review"})]
    result = run_scenario(FakeModel(unasked), scenario_named("a1_topic_en"))
    assert result.ok is False and result.checks["no_action_unasked"] is False
