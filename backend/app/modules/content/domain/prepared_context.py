"""Shared gate for learner-visible, sense-bound prepared meaning."""


def prepared_context(
    diagnostics: dict | None, *, concept_id: str, sense_key: str,
    source_language_code: str, support_language_code: str | None,
) -> dict | None:
    if not support_language_code:
        return None
    data = diagnostics or {}
    per_language = data.get("enrichments")
    enrichment = per_language.get(support_language_code) if isinstance(per_language, dict) else None
    if enrichment is None:
        enrichment = data.get("enrichment")
    if not isinstance(enrichment, dict):
        return None
    if (enrichment.get("concept_id") != concept_id
            or enrichment.get("concept_sense_key") != sense_key
            or enrichment.get("source_language_code") != source_language_code
            or enrichment.get("target_language_code") != support_language_code):
        return None
    meaning, explanation = enrichment.get("contextual_meaning"), enrichment.get("explanation")
    if (not isinstance(meaning, str) or not meaning.strip()
            or explanation is not None
            and (not isinstance(explanation, str) or not explanation.strip())):
        return None
    return enrichment


def sense_translated_meaning(diagnostics: dict | None, support_language_code: str | None) -> tuple[str | None, str | None]:
    """M1 S7d: an occurrence's meaning and part of speech in the support language, only when that
    meaning was translated from a dictionary sense (never an unverified model meaning)."""
    enrichment = ((diagnostics or {}).get("enrichments") or {}).get(support_language_code or "")
    if not isinstance(enrichment, dict) or enrichment.get("meaning_provenance") != "translated_from_sense":
        return None, None
    meaning = " ".join(str(enrichment.get("contextual_meaning") or "").split())
    sense = enrichment.get("dictionary_sense") if isinstance(enrichment.get("dictionary_sense"), dict) else {}
    return (meaning or None), sense.get("pos")
