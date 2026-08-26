"""Résolution de références de sélection ; les données restent dans les services existants."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from core.file_identity import require_file_id
from selection.context import SelectionContext


class SelectionResolver(Protocol):
    def resolve_file(self, context: SelectionContext) -> Mapping[str, Any] | None: ...


class FileSelectionRegistry:
    """Index paresseux de références aux fichiers du rapport, sans copier leurs données."""

    def __init__(self) -> None:
        self._records: Sequence[Mapping[str, Any]] = ()
        self._known_records: dict[str, Mapping[str, Any]] = {}

    def set_records(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records = records
        self._known_records.clear()

    def identifier_for(self, record: Mapping[str, Any]) -> str:
        identifier = require_file_id(record)
        self._known_records[identifier] = record
        return identifier

    def record_for(self, identifier: str) -> Mapping[str, Any] | None:
        cached = self._known_records.get(identifier)
        if cached is not None:
            return cached
        # Recherche de compatibilité différée : l'index global n'est pas créé à l'ouverture.
        for record in self._records:
            if require_file_id(record) == identifier:
                self._known_records[identifier] = record
                return record
        return None


class FileSelectionResolver:
    """Résout le fichier lié à un contexte sans connaître les détails de son affichage."""

    def __init__(self, registry: FileSelectionRegistry) -> None:
        self._registry = registry

    def resolve_file(self, context: SelectionContext) -> Mapping[str, Any] | None:
        if context.subject_kind == "file":
            return self._registry.record_for(context.subject_id)
        file_id = context.related_ids.get("file_id")
        return self._registry.record_for(file_id) if file_id else None
