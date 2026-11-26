"""The lookups that feed the Notebook."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.modules.identity.contracts import CurrentUser

USER = CurrentUser(id=uuid4())


def test_the_companion_logs_every_lookup_and_writes_nothing_else():
    from app.modules.learning.application.agent.ports import DictionarySense, DictionaryWord
    from app.modules.learning.application.agent.session import AgentSession
    from app.modules.learning.application.agent.tools import ToolRegistry
    log = Mock()
    tools = ToolRegistry(learning_log=log)
    ticket = SimpleNamespace(user_id=USER.id, language_code="en", items=[], scenario_id=None, region_lines=())
    session = AgentSession(user=USER, prepared=SimpleNamespace(ticket=ticket))
    one = DictionaryWord(headword="nap", senses=(DictionarySense("A short sleep.", "noun", "s:nap"),), entry_id=uuid4())
    two = DictionaryWord(headword="run", senses=(DictionarySense("To move.", "verb", "s:r1"),
                                                 DictionarySense("To manage.", "verb", "s:r2")), entry_id=uuid4())
    tools.record_lookup(session, "run")
    tools.record_lookup(session, "nap")
    tools.record_lookup(session, "nap")
    # Every lookup is a learning fact the agent can read back later (one log row per word and conversation).
    assert [call.args[0].kind for call in log.record.call_args_list] == ["lookup", "lookup", "lookup"]


def test_a_lookup_stores_its_vietnamese_sense_once():
    from tests.content.test_word_lookup import GIVE, GIVE_UP, GAVE, lookup, service as lookup_service
    built, segment = lookup_service("I never gave up.", GIVE_UP, GAVE, GIVE,
                                    outputs=({"sense_id": "enwikt:giveup1", "meaning": " bỏ  cuộc ", "note": None},))
    built.translations = Mock()
    lookup(built, segment, 13, 15)
    [rows] = built.translations.save.call_args.args
    assert rows == [{"dictionary_entry_id": GIVE_UP.id, "sense_id": "enwikt:giveup1", "support_language_code": "vi",
                     "language_code": "en", "headword": "give up", "part_of_speech": "verb", "meaning": "bỏ cuộc",
                     "origin": "lookup", "prompt_version": "word_lookup_sense_v2"}]
    built.translations.save.side_effect = RuntimeError("database unavailable")
    built2, segment2 = lookup_service("I never gave up.", GIVE_UP, GAVE, GIVE,
                                      outputs=({"sense_id": "enwikt:giveup1", "meaning": "bỏ cuộc", "note": None},))
    built2.translations = built.translations
    assert lookup(built2, segment2, 13, 15).meaning == "bỏ cuộc"  # a failed store never fails the lookup
