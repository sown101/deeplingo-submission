from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4


from app.bootstrap.wiring.learner_profile import Grammar, Signals, Usage, Vocabulary, DeclaredLevel
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.domain.agent_signals import SignalKind
from app.modules.learner.domain.profile_snapshot import VocabularySection
from app.modules.practice.application.grammar import GrammarService

USER = CurrentUser(id=uuid4())


def _signal(kind, code, count=1, language="en"):
    return SimpleNamespace(kind=kind, code=code, usage_count=count, language_code=language)


class _Signals:
    def __init__(self, consent, rows):
        self.consent, self.rows = consent, rows

    def has_consent(self, user_id):
        return self.consent

    def signals(self, user_id):
        return SimpleNamespace(signals=self.rows)


def test_signals_are_empty_without_consent_even_when_some_were_stored():
    rows = [_signal(SignalKind.ERROR_TYPE, "articles", 4)]
    section = Signals(_Signals(False, rows)).signals(USER, "en")
    assert (section.error_kinds, section.interests, section.goals) == ((), (), ())


def test_signals_keep_the_language_order_by_use_and_a_small_cap():
    rows = [_signal(SignalKind.ERROR_TYPE, code, count) for code, count in
            [("articles", 1), ("prepositions", 9), ("word_order", 9), ("pronouns", 3), ("plural_forms", 2),
             ("conjunctions", 2), ("word_choice", 1)]]
    rows += [_signal(SignalKind.TOPIC, "travel"), _signal(SignalKind.GOAL, "exam"),
             _signal(SignalKind.ERROR_TYPE, "measure_words", 50, language="zh")]
    section = Signals(_Signals(True, rows)).signals(USER, "en")
    assert section.error_kinds == ("prepositions", "word_order", "pronouns", "conjunctions", "plural_forms")
    assert section.interests == ("travel",) and section.goals == ("exam",)


def test_usage_counts_words_by_rung_and_leaves_suspended_words_out():
    class Targets:
        def list_for_user(self, user_id, *, language_code=None, status=None):
            assert language_code == "en"
            return [{"rung": 1, "status": "active"}, {"rung": 1, "status": "backlog"}, {"rung": 4, "status": "active"},
                    {"rung": None, "status": "active"}, {"rung": 3, "status": "suspended"}]

    assert Usage(Targets()).words_by_rung(USER, "en") == {1: 2, 4: 1, 0: 1}


def test_the_vocabulary_of_another_language_is_not_used():
    views = [SimpleNamespace(language_code="zh", known_words=9, library_words=20, is_estimate=True)]
    coverage = SimpleNamespace(vocabulary=lambda user: views)
    assert Vocabulary(coverage).vocabulary(USER, "en") is None
    assert Vocabulary(coverage).vocabulary(USER, "zh") == VocabularySection(known_words=9, library_words=20)


def test_the_declared_level_is_read_for_the_asked_language():
    store = Mock()
    store.get_by_language_for_user.return_value = SimpleNamespace(declared_level="B1")
    assert DeclaredLevel(store).declared_level(USER, "en") == "B1"
    store.get_by_language_for_user.assert_called_once_with(user_id=USER.id, language_code="en")
    store.get_by_language_for_user.return_value = None
    assert DeclaredLevel(store).declared_level(USER, "en") is None


def test_grammar_counts_points_practised_at_least_once_across_levels():
    profiles = Mock()
    profiles.get_profile_for_user.return_value = SimpleNamespace(support_language_code="vi")
    banks, progress, requests = Mock(), Mock(), Mock()
    banks.for_language.return_value = [
        SimpleNamespace(level=level, language="en", support_language="vi", require_approval=Mock(),
                        points=[SimpleNamespace(key=key) for key in keys])
        for level, keys in [("A1", ("a", "b")), ("A2", ("c",))]
    ]
    progress.for_language.return_value = {"a": {"attempts": 2}, "b": {"attempts": 0}, "c": {"attempts": 1}}
    service = GrammarService(profiles=profiles, banks=banks, progress=progress, requests=requests)

    section = Grammar(service).grammar_summary(USER, "en")

    assert (section.practised_points, section.total_points, section.practised_by_level) == (2, 3, {"A1": 1, "A2": 1})
    progress.for_language.assert_called_once_with(USER.id, "en")
    banks.for_language.assert_called_once_with("en", "vi")
    requests.study_requests.assert_not_called()


def test_grammar_of_a_language_without_approved_banks_is_unavailable():
    service = Mock()
    service.practice_counts.return_value = (0, {})
    assert Grammar(service).grammar_summary(USER, "en") is None
