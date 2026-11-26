"""One in-memory store shared by the practice tests. It does what the SQL functions of migration
20261114120000_review_engine do: decks per language, the pass rule, idempotent answers, grade + FSRS + one
learning-log row together, and closing study requests on a correct answer."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.activity.domain.models import ActivityEntry
from app.modules.practice.application.grammar import GrammarService
from app.modules.practice.application.review import ReviewService
from app.modules.practice.domain.exercises import SentenceSource, WordCard
from app.modules.review.infrastructure.fsrs_adapter import FSRSAdapter
from tests.activity.fakes import START, Clock, make_activity

USER = UUID("00000000-0000-0000-0000-0000000000a1")
OTHER = UUID("00000000-0000-0000-0000-0000000000b2")


def word(text: str, language: str = "en", *, meaning: str | None = None, sentence: str | None = None,
         reading: str | None = None, concept_id: UUID | None = None) -> WordCard:
    source = SentenceSource(text=sentence, target_form=text, origin="video", library_item_id=uuid4(),
                            start_ms=1200) if sentence else None
    return WordCard(concept_id=concept_id or uuid4(), language_code=language, text=text, reading=reading,
                    meaning=meaning, sentence=source)


MEANING_POOL = [("run", "chạy"), ("eat", "ăn uống"), ("sleep", "ngủ say"), ("book", "quyển sách"),
                ("river", "dòng sông")]
WORD_POOL = ["apple", "table", "window", "garden", "pencil"]


class FakeCards:
    def __init__(self, cards: list[WordCard]):
        self.by_id = {card.concept_id: card for card in cards}

    def cards(self, user_id, language_code, concept_ids):
        return {concept_id: self.by_id[concept_id] for concept_id in concept_ids
                if concept_id in self.by_id and self.by_id[concept_id].language_code == language_code}

    def meaning_pool(self, user_id, language_code):
        return MEANING_POOL

    def word_pool(self, language_code):
        return WORD_POOL


class FakeDeckStore:
    def __init__(self, log, requests, clock):
        self.log, self.requests, self.clock = log, requests, clock
        self.saved: dict[tuple[UUID, UUID], dict] = {}
        self.states: dict[tuple[UUID, UUID], dict] = {}
        self.events: list[dict] = []
        self.conflicts_left = 0

    def save(self, user_id: UUID, card: WordCard, *, eligible: bool = True, saved_at: datetime | None = None):
        self.saved[(user_id, card.concept_id)] = {"language_code": card.language_code, "eligible": eligible,
                                                  "saved_at": saved_at or self.clock()}

    def make_due(self, user_id: UUID, concept_id: UUID, *, days_ago: int = 1):
        state = self.states[(user_id, concept_id)]
        state["due_at"] = (self.clock() - timedelta(days=days_ago)).isoformat()

    def _rows(self, user_id):
        return [(concept, row) for (owner, concept), row in self.saved.items() if owner == user_id and row["eligible"]]

    def _due(self, user_id, concept):
        state = self.states.get((user_id, concept))
        return None if state is None else datetime.fromisoformat(state["due_at"])

    def deck_counts(self, user_id):
        decks: dict[str, dict] = {}
        for concept, row in self._rows(user_id):
            deck = decks.setdefault(row["language_code"], {"language_code": row["language_code"], "due_count": 0,
                                                           "new_count": 0, "total_count": 0})
            due = self._due(user_id, concept)
            deck["total_count"] += 1
            deck["new_count" if due is None else "due_count"] += 1 if due is None or due <= self.clock() else 0
        return list(decks.values())

    def deck_cards(self, user_id, language_code, *, limit, concept_ids):
        rows = []
        for concept, row in self._rows(user_id):
            if row["language_code"] != language_code:
                continue
            due = self._due(user_id, concept)
            if concept_ids is None and due is not None and due > self.clock():
                continue
            if concept_ids is not None and concept not in concept_ids:
                continue
            rows.append({"concept_id": concept, "due_at": due, "is_new": due is None, "saved_at": row["saved_at"]})
        rows.sort(key=lambda item: (item["is_new"], item["due_at"] or START, -item["saved_at"].timestamp()))
        return rows[:limit]

    def _log_rows(self, user_id, concept_id):
        return [entry for entry in self.log.entries if entry.user_id == user_id and entry.item_type == "concept"
                and entry.item_id == str(concept_id) and entry.source_type == "review_deck"]

    def answer_context(self, user_id, concept_id, pass_id):
        row = self.saved.get((user_id, concept_id))
        rows = self._log_rows(user_id, concept_id)
        last = rows[-1] if rows else None
        return {
            "language_code": row["language_code"] if row else None, "eligible": bool(row and row["eligible"]),
            "review_state": dict(self.states[(user_id, concept_id)]) if (user_id, concept_id) in self.states else None,
            "scheduled_in_pass": pass_id is not None and any(
                entry.source_id == pass_id and entry.detail.get("scheduled") is True for entry in rows),
            "last_result": {"outcome": last.outcome, "fast": last.detail.get("fast")} if last else None,
        }

    def submit_answer(self, user_id, concept_id, transition, log):
        existing = next((entry for entry in self.log.entries
                         if entry.user_id == user_id and entry.client_event_id == log["client_event_id"]), None)
        if existing is not None:
            return {"status": "duplicate", "outcome": existing.outcome, "score": existing.score,
                    "detail": existing.detail}
        row = self.saved.get((user_id, concept_id))
        if row is None or not row["eligible"] or row["language_code"] != log["language_code"]:
            return {"status": "skipped"}
        if self.conflicts_left:
            self.conflicts_left -= 1
            return {"status": "conflict"}
        pass_id = log.get("source_id")
        scheduled = False
        state = self.states.get((user_id, concept_id))
        if transition is not None and not any(entry.source_id == pass_id and entry.detail.get("scheduled") is True
                                              for entry in self._log_rows(user_id, concept_id)):
            previous, target = transition["previous"], transition["next"]
            if (state is None) != transition["create"] or (state and state["version"] != previous["version"]):
                return {"status": "conflict"}
            self.states[(user_id, concept_id)] = {
                "id": target["review_state_id"], "user_id": str(user_id), "concept_id": str(concept_id),
                "review_mode": "concept_to_meaning", "fsrs_state": target["fsrs_state"],
                "stability": target["stability"], "difficulty": target["difficulty"],
                "elapsed_days": target["elapsed_days"], "scheduled_days": target["scheduled_days"],
                "reps": target["reps"], "lapses": target["lapses"], "version": target["version"],
                "due_at": target["due_at"], "last_reviewed_at": target["last_reviewed_at"],
                "language_code": row["language_code"]}
            self.events.append(transition["event"])
            scheduled = True
        state = self.states.get((user_id, concept_id))
        next_due = state["due_at"] if state else None
        self.log.insert_once(ActivityEntry(
            user_id=user_id, language_code=row["language_code"], client_event_id=log["client_event_id"],
            kind=log["kind"], outcome=log["outcome"], item_type="concept", item_id=str(concept_id),
            source_type="review_deck", source_id=pass_id, score=log.get("score"),
            detail={**log["detail"], "scheduled": scheduled, "next_review_at": next_due}))
        closed = 0
        if log["outcome"] == "correct":
            closed = self.requests.close_open_for_item(user_id=user_id, language_code=row["language_code"],
                                                       item_type="concept", item_id=str(concept_id),
                                                       closed_at=self.clock())
        return {"status": "applied" if scheduled else "graded", "next_review_at": next_due, "requests_closed": closed}


    def latest_pronunciation(self, user_id, concept_id):
        rows = [entry for entry in self._log_rows(user_id, concept_id) if entry.kind == "pronunciation"]
        if not rows:
            return None
        return {"score": rows[-1].score, "outcome": rows[-1].outcome, "detail": rows[-1].detail,
                "occurred_at": self.clock().isoformat()}


class FakeGrammarProgress:
    """learner_grammar_progress and the grammar SQL functions over the same in-memory log and requests."""

    def __init__(self, log, requests, clock):
        self.log, self.requests, self.clock = log, requests, clock
        self.rows: dict[tuple[UUID, str, str], dict] = {}

    def for_language(self, user_id, language_code):
        return {key: row for (owner, language, key), row in self.rows.items()
                if owner == user_id and language == language_code}

    def _row(self, user_id, language_code, grammar_key):
        return self.rows.setdefault((user_id, language_code, grammar_key), {
            "grammar_key": grammar_key, "lesson_learned_at": None, "attempts": 0, "correct_count": 0,
            "last_attempt_at": None, "last_correct_at": None})

    def record_answer(self, user_id, language_code, grammar_key, log):
        existing = next((entry for entry in self.log.entries
                         if entry.user_id == user_id and entry.client_event_id == log["client_event_id"]), None)
        if existing is not None:
            return {"status": "duplicate", "outcome": existing.outcome, "detail": existing.detail}
        self.log.insert_once(ActivityEntry(
            user_id=user_id, language_code=language_code, client_event_id=log["client_event_id"],
            kind="grammar_exercise", outcome=log["outcome"], item_type="grammar_point", item_id=grammar_key,
            source_type="notebook", detail=log["detail"]))
        row = self._row(user_id, language_code, grammar_key)
        row["attempts"] += 1
        row["last_attempt_at"] = self.clock()
        closed = 0
        if log["outcome"] == "correct":
            row["correct_count"] += 1
            row["last_correct_at"] = self.clock()
            closed = self.requests.close_open_for_item(user_id=user_id, language_code=language_code,
                                                       item_type="grammar_point", item_id=grammar_key,
                                                       closed_at=self.clock())
        return {"status": "recorded", "requests_closed": closed}

    def record_lesson(self, user_id, language_code, grammar_key, client_event_id):
        self.log.insert_once(ActivityEntry(
            user_id=user_id, language_code=language_code, client_event_id=client_event_id, kind="grammar_lesson",
            outcome="done", item_type="grammar_point", item_id=grammar_key, source_type="notebook"))
        row = self._row(user_id, language_code, grammar_key)
        row["lesson_learned_at"] = row["lesson_learned_at"] or self.clock()
        return {"status": "recorded", "lesson_learned_at": row["lesson_learned_at"]}


def make_review(cards: list[WordCard], *, user_id: UUID = USER, save: bool = True):
    """(service, store, log, requests, clock): the real ReviewService and FSRS over in-memory stores."""
    activity, log, requests, clock = make_activity()
    store = FakeDeckStore(log, requests, clock)
    if save:
        for card in cards:
            store.save(user_id, card)
    service = ReviewService(store=store, cards=FakeCards(cards), adapter=FSRSAdapter(), clock=clock)
    return SimpleNamespace(service=service, store=store, log=log, requests=requests, clock=clock, activity=activity)


def make_grammar(banks, *, language="en", support="vi"):
    activity, log, requests, clock = make_activity()
    progress = FakeGrammarProgress(log, requests, clock)
    profile = SimpleNamespace(language_code=language, support_language_code=support)
    service = GrammarService(profiles=SimpleNamespace(get_profile_for_user=lambda user_id: profile),
                             banks=SimpleNamespace(for_language=lambda lang, sup: [
                                 bank for bank in banks if bank.language == lang and bank.support_language == sup]),
                             progress=progress, requests=activity)
    return SimpleNamespace(service=service, progress=progress, log=log, requests=requests, clock=clock,
                           activity=activity, profile=profile)


__all__ = ["Clock", "USER", "OTHER", "word", "make_review", "make_grammar"]
