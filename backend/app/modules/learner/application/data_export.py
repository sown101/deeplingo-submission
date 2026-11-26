"""The learner's own data as one JSON document (privacy notice: right to access).

Each module exports the learner-owned rows it owns through a section that satisfies
LearnerDataSection; bootstrap wires the list. Shared content (videos, dictionary,
Concepts) is not the learner's data and appears only as labels for referenced Concepts.
Hidden answers, rubrics, raw AI diagnostics and internal scheduling parameters are left out.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

EXPORT_FORMAT = "deeplingo-learner-export-v1"


class LearnerDataSection(Protocol):
    name: str

    def export(self, user_id: UUID) -> Any: ...


class ConceptLabelReader(Protocol):
    def labels(self, concept_ids: list[str]) -> dict[str, str]: ...


class LearnerDataExportService:
    def __init__(self, *, sections: list[LearnerDataSection], concept_labels: ConceptLabelReader | None = None):
        names = [section.name for section in sections]
        if len(names) != len(set(names)):
            raise ValueError("Export section names must be unique")
        self.sections = sections
        self.concept_labels = concept_labels

    def export(self, user_id: UUID) -> dict[str, Any]:
        document: dict[str, Any] = {
            "format": EXPORT_FORMAT,
            "exported_at": datetime.now(UTC).isoformat(),
            "user_id": str(user_id),
        }
        for section in self.sections:
            document[section.name] = section.export(user_id)
        concept_ids = sorted(_concept_ids(document))
        document["concepts"] = self.concept_labels.labels(concept_ids) if self.concept_labels and concept_ids else {}
        return document


def _concept_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "concept_id" and isinstance(item, str):
                found.add(item)
            else:
                found |= _concept_ids(item)
    elif isinstance(value, list):
        for item in value:
            found |= _concept_ids(item)
    return found
