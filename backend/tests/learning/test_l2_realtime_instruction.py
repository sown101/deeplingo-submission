from app.modules.learning.application.agent.prompts import build_voice_instruction
from app.modules.learning.domain.companion import CompanionItem


def test_instruction_uses_selected_languages_without_inventing_a_learner_level():
    instruction = build_voice_instruction(
        mode="topic",
        learning_language="zh", support_language="en", topic="At the airport",
        items=[CompanionItem("c1", "机场", "airport", ("机场",), False)],
        excerpt="我们到机场了。",
    )
    assert "A2" not in instruction
    assert "Vietnamese" not in instruction
    assert "Chinese" in instruction and "English" in instruction
    assert "机场" in instruction and "我们到机场了。" in instruction


def test_selected_words_are_practised_through_conversation_not_a_list_recitation():
    instruction = build_voice_instruction(
        mode="topic",
        learning_language="en", support_language="vi", topic="Travel",
        items=[CompanionItem("c1", "airport", "sân bay", ("airport",), False)],
        excerpt=None,
    )
    assert "one selected word at a time" in instruction
    assert "do not recite the word list" in instruction.lower()
    assert "ONE" in instruction
    assert "never mention scores" in instruction
