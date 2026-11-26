"""What the learner has done, summed from the learning log and the review states (PRD 8.10, TARGET_DESIGN section 8).

Pure arithmetic over rows of one learner. The same rows in, the same numbers out; nothing here reads a store or
writes a result.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict

WINDOW_DAYS = 365
GRADED_OUTCOMES = frozenset({"correct", "incorrect", "partial"})
MAX_WEAK_WORDS = 10
WEEKS_SHOWN = 26
REGION_KINDS = frozenset({"dictation", "shadowing", "region_question"})
CARD_STATES = ("new", "learning", "review", "relearning")


@dataclass(frozen=True)
class LogRow:
    """The columns of one log row that progress reads."""
    language_code: str
    kind: str
    outcome: str
    occurred_at: datetime
    item_type: str | None = None
    item_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    seconds: int | None = None


@dataclass(frozen=True)
class PronunciationRow:
    """One scored practice: the average Azure scores of its turns and the words that were weak. Completeness and
    prosody are empty for rows from before they were kept and for languages Azure does not score them in."""
    occurred_at: datetime
    pronunciation: float | None = None
    accuracy: float | None = None
    fluency: float | None = None
    completeness: float | None = None
    prosody: float | None = None
    weak_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class CardRow:
    language_code: str
    state: str
    due_at: datetime | None


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StreakView(_View):
    current: int
    longest: int
    active_days: int


class HeatDay(_View):
    date: date
    count: int


class DeckProgress(_View):
    language_code: str
    total: int
    due: int
    new: int
    learning: int
    review: int
    relearning: int


class KindAccuracy(_View):
    kind: str
    attempts: int
    correct: int
    accuracy: float  # percent of attempts that were correct


class PronunciationDay(_View):
    """Average of each score over the practices of one day; a score nobody recorded that day is None."""
    date: date
    pronunciation: float | None
    accuracy: float | None
    fluency: float | None
    completeness: float | None
    prosody: float | None
    sessions: int


class GrammarProgress(_View):
    learned: int
    done_correctly: int


class SpeakingWeek(_View):
    week_start: date  # the Monday
    minutes: float


class SpeakingProgress(_View):
    sessions: int
    minutes: float
    weeks: list[SpeakingWeek]  # the last weeks that have speaking time, oldest first


class ProgressView(_View):
    language: str | None  # the filter; None means every language
    languages: list[str]  # the languages the learner studies, for the filter
    utc_offset_minutes: int
    window_days: int
    streak: StreakView
    heatmap: list[HeatDay]  # days with at least one log row, oldest first
    cards: list[DeckProgress]
    accuracy: list[KindAccuracy]
    pronunciation: list[PronunciationDay]  # oldest first
    weak_words: list[str]  # the words most often weak, most frequent first
    grammar: GrammarProgress
    regions_completed: int
    speaking: SpeakingProgress


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _streaks(days: set[date], today: date) -> tuple[int, int]:
    """Current: consecutive days ending today, or yesterday when today has nothing yet. Longest: the best run."""
    current, cursor = 0, today if today in days else today - timedelta(days=1)
    while cursor in days:
        current, cursor = current + 1, cursor - timedelta(days=1)
    longest = run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest, previous = max(longest, run), day
    return current, longest




METRICS = ("pronunciation", "accuracy", "fluency", "completeness", "prosody")


@dataclass(frozen=True)
class ScoreDay:
    """The scored practices of one local day: how many, and per metric the sum and count of recorded values."""
    sessions: int
    sums: dict[str, tuple[float, int]]


@dataclass(frozen=True)
class ProgressTotals:
    """Everything progress shows, already summed for one learner, one language filter, one window and one offset.

    Production sums it in SQL (`v3.learner_progress_totals`); `totals_from_rows` is the same arithmetic over rows and
    is the reference the SQL must match."""
    days: dict[date, int]  # local day -> log rows, inside the window
    graded: dict[str, tuple[int, int]]  # kind -> (attempts, correct)
    grammar_learned: int
    grammar_correct: int
    regions: int
    speaking_sessions: int
    speaking_seconds: int
    week_seconds: dict[date, int]  # Monday -> speaking seconds
    cards: dict[str, dict[str, int]]  # language -> state or "due" -> count
    scores: dict[date, ScoreDay]
    weak: dict[str, int]  # weak word -> times
    data_languages: tuple[str, ...]  # languages that have log rows (since the window start) or cards


def _window(now: datetime, utc_offset_minutes: int) -> tuple[timedelta, date, date]:
    offset = timedelta(minutes=utc_offset_minutes)
    today = (as_utc(now) + offset).date()
    return offset, today - timedelta(days=WINDOW_DAYS - 1), today


def totals_from_rows(rows: list[LogRow], cards: list[CardRow], pronunciation: list[PronunciationRow] | tuple = (),
                     *, now: datetime, utc_offset_minutes: int) -> ProgressTotals:
    """The reference arithmetic: the rows of one learner already narrowed to the language filter and to the time since
    one day before the window (every local offset)."""
    offset, first, today = _window(now, utc_offset_minutes)
    now = as_utc(now)

    def local_day(value: datetime) -> date:
        return (as_utc(value) + offset).date()

    data_languages = tuple(sorted({row.language_code for row in rows} | {card.language_code for card in cards}))
    rows = [row for row in rows if first <= local_day(row.occurred_at) <= today]
    graded: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        if row.outcome in GRADED_OUTCOMES:
            graded[row.kind][0] += 1
            graded[row.kind][1] += row.outcome == "correct"

    def points(kind: str, outcome: str | None = None) -> int:
        return len({(row.language_code, row.item_id) for row in rows
                    if row.kind == kind and row.item_type == "grammar_point" and row.item_id
                    and outcome in (None, row.outcome)})

    sessions = [row for row in rows if row.kind == "speaking_session"]
    week_seconds: Counter = Counter()
    for row in sessions:
        day = local_day(row.occurred_at)
        week_seconds[day - timedelta(days=day.weekday())] += row.seconds or 0
    decks: dict[str, Counter] = defaultdict(Counter)
    for card in cards:
        deck = decks[card.language_code]
        deck[card.state] += 1
        if card.due_at is not None and as_utc(card.due_at) <= now:
            deck["due"] += 1
    scores: dict[date, list[PronunciationRow]] = defaultdict(list)
    weak: Counter = Counter()
    for item in pronunciation:
        if first <= local_day(item.occurred_at) <= today:
            scores[local_day(item.occurred_at)].append(item)
            weak.update(item.weak_words)
    return ProgressTotals(
        days=dict(Counter(local_day(row.occurred_at) for row in rows)),
        graded={kind: (n, c) for kind, (n, c) in graded.items()},
        grammar_learned=points("grammar_lesson"), grammar_correct=points("grammar_exercise", "correct"),
        regions=len({(row.language_code, row.source_id) for row in rows
                     if row.source_type == "video_region" and row.source_id and row.kind in REGION_KINDS}),
        speaking_sessions=len(sessions), speaking_seconds=sum(row.seconds or 0 for row in sessions),
        week_seconds=dict(week_seconds),
        cards={code: dict(deck) for code, deck in decks.items()},
        scores={day: ScoreDay(sessions=len(items), sums={
            metric: (sum(v for v in (getattr(i, metric) for i in items) if v is not None),
                     sum(1 for i in items if getattr(i, metric) is not None)) for metric in METRICS})
            for day, items in scores.items()},
        weak=dict(weak), data_languages=data_languages,
    )


def _mean(total: tuple[float, int]) -> float | None:
    value, count = total
    return round(value / count, 1) if count else None


def build_progress(totals: ProgressTotals, languages: list[str], *, language: str | None, now: datetime,
                   utc_offset_minutes: int) -> ProgressView:
    _, _, today = _window(now, utc_offset_minutes)
    current, longest = _streaks(set(totals.days), today)
    decks = []
    for code, counts in sorted(totals.cards.items()):
        states = {state: counts.get(state, 0) for state in CARD_STATES}
        states["new"] += sum(n for state, n in counts.items() if state not in CARD_STATES and state != "due")
        decks.append(DeckProgress(language_code=code, total=sum(states.values()), due=counts.get("due", 0), **states))
    return ProgressView(
        language=language,
        languages=languages,
        utc_offset_minutes=utc_offset_minutes,
        window_days=WINDOW_DAYS,
        streak=StreakView(current=current, longest=longest, active_days=len(totals.days)),
        heatmap=[HeatDay(date=day, count=count) for day, count in sorted(totals.days.items())],
        cards=decks,
        accuracy=[KindAccuracy(kind=kind, attempts=n, correct=c, accuracy=round(100 * c / n, 1))
                  for kind, (n, c) in sorted(totals.graded.items()) if n],
        pronunciation=[PronunciationDay(date=day, sessions=item.sessions,
                                        **{metric: _mean(item.sums.get(metric, (0, 0))) for metric in METRICS})
                       for day, item in sorted(totals.scores.items())],
        weak_words=[word for word, _ in sorted(totals.weak.items(), key=lambda pair: (-pair[1], pair[0]))[:MAX_WEAK_WORDS]],
        grammar=GrammarProgress(learned=totals.grammar_learned, done_correctly=totals.grammar_correct),
        regions_completed=totals.regions,
        speaking=SpeakingProgress(sessions=totals.speaking_sessions,
                                  minutes=round(totals.speaking_seconds / 60, 1),
                                  weeks=[SpeakingWeek(week_start=week, minutes=round(seconds / 60, 1))
                                         for week, seconds in sorted(totals.week_seconds.items())[-WEEKS_SHOWN:]]),
    )
