"""Pronunciation scores of a practice (PRD FR-4.2): best effort, never breaks the practice. That the practice
happened is in the learning log."""
from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def _average(results, name: str) -> float | None:
    """The mean of one score over the results that have it; Azure scores prosody only for some languages."""
    values = [float(value) for item in results if (value := getattr(item.scores, name, None)) is not None]
    return round(sum(values) / len(values), 1) if values else None


def record_pronunciation(scores, user_id: UUID, *, language_code: str, source: str, results) -> None:
    """One row per practice: average scores and weak words. Never audio or what was said; a failure is not the learner's."""
    if scores is None or not results:
        return
    try:
        weak = [word.word for item in results for word in item.words if word.accuracy < 60]
        scores.record(user_id, language_code=language_code, source=source, pronunciation=_average(results, "pronunciation"),
                      accuracy=_average(results, "accuracy"), fluency=_average(results, "fluency"),
                      completeness=_average(results, "completeness"), prosody=_average(results, "prosody"),
                      weak_words=list(dict.fromkeys(weak))[:10])
    except Exception as exc:
        logger.warning("pronunciation score not recorded error=%s", type(exc).__name__)
