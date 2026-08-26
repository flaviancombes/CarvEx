"""Résolution centralisée des identités métier transversales.

Ce module est la seule frontière autorisée entre les représentations d'un
fichier (record importé, événement Timeline, bookmark historique ou Item
Investigation) et sa référence canonique ``file/file_id``. Il ne dépend pas de
Qt, ne modifie aucune donnée et ne connaît ni stockage ni widget.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from bookmarks.model import Bookmark, BookmarkKey
from core.file_identity import FileIdentityError, require_file_id
from investigation.item import InvestigationItem
from investigation.target_ref import InvestigationTargetRef
from selection.resolver import FileSelectionRegistry
from timeline.event import TimelineEvent


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    """Résultat léger d'une résolution, sans copie de l'entité source."""

    kind: str
    identifier: str
    file_record: Mapping[str, Any] | None = None
    timeline_event: TimelineEvent | None = None
    investigation_item: InvestigationItem | None = None

    @property
    def is_file(self) -> bool:
        return self.kind == "file"


class CanonicalEntityResolver:
    """Convertit les représentations connues vers une identité canonique.

    Les dépendances vers Timeline et Investigation sont injectées comme de
    simples lookups publics. Ainsi le résolveur reste utilisable hors de l'UI
    et n'introduit aucun couplage vers les repositories ou les stores.
    """

    def __init__(self, files: FileSelectionRegistry | None = None) -> None:
        self._files = files or FileSelectionRegistry()
        self._timeline_event_lookup: Callable[[str], TimelineEvent | None] | None = None
        self._investigation_item_lookup: Callable[[str], InvestigationItem | None] | None = None

    def set_timeline_event_lookup(self, lookup: Callable[[str], TimelineEvent | None] | None) -> None:
        self._timeline_event_lookup = lookup

    def set_investigation_item_lookup(self, lookup: Callable[[str], InvestigationItem | None] | None) -> None:
        self._investigation_item_lookup = lookup

    def resolve(self, entity: object) -> CanonicalEntity | None:
        """Résout un objet connu sans jamais recourir au nom ou au chemin."""
        if isinstance(entity, TimelineEvent):
            return self._resolve_timeline_event(entity)
        if isinstance(entity, Bookmark):
            return self._resolve_bookmark(entity)
        if isinstance(entity, InvestigationItem):
            return self.resolve_target(entity.subject_kind, entity.subject_id, investigation_item=entity)
        if isinstance(entity, InvestigationTargetRef):
            return self.resolve_target(entity.target_kind, entity.target_id)
        if isinstance(entity, Mapping):
            return self._resolve_file_record(entity)
        return None

    def resolve_target(
        self,
        kind: str,
        identifier: str,
        *,
        investigation_item: InvestigationItem | None = None,
    ) -> CanonicalEntity | None:
        """Résout une référence légère, y compris les références historiques."""
        if kind == "file":
            file_id = self._valid_file_id(identifier)
            return CanonicalEntity("file", file_id, self._files.record_for(file_id)) if file_id is not None else None
        if kind == "timeline_event":
            if self._timeline_event_lookup is None:
                return None
            event = self._timeline_event_lookup(identifier)
            return self._resolve_timeline_event(event) if event is not None else None
        if kind == "item":
            item = investigation_item
            if item is None and self._investigation_item_lookup is not None:
                item = self._investigation_item_lookup(identifier)
            if item is None:
                return None
            resolved = self.resolve_target(item.subject_kind, item.subject_id, investigation_item=item)
            if resolved is None:
                return CanonicalEntity("item", identifier, investigation_item=item)
            return CanonicalEntity(
                resolved.kind,
                resolved.identifier,
                resolved.file_record,
                resolved.timeline_event,
                item,
            )
        return CanonicalEntity(kind, identifier, investigation_item=investigation_item)

    def file_id_for(self, entity: object) -> str | None:
        resolved = self.resolve(entity)
        return resolved.identifier if resolved is not None and resolved.is_file else None

    def bookmark_key_for(self, entity: object) -> BookmarkKey | None:
        file_id = self.file_id_for(entity)
        return BookmarkKey("file", file_id) if file_id is not None else None

    def _resolve_file_record(self, record: Mapping[str, Any]) -> CanonicalEntity | None:
        try:
            file_id = require_file_id(record)
        except FileIdentityError:
            return None
        self._files.identifier_for(record)
        return CanonicalEntity("file", file_id, record)

    @staticmethod
    def _valid_file_id(identifier: str) -> str | None:
        try:
            return str(UUID(str(identifier)))
        except (TypeError, ValueError, AttributeError):
            return None

    def _resolve_timeline_event(self, event: TimelineEvent) -> CanonicalEntity | None:
        if event.file_record is None:
            return None
        resolved = self._resolve_file_record(event.file_record)
        if resolved is None:
            return None
        return CanonicalEntity("file", resolved.identifier, resolved.file_record, event)

    def _resolve_bookmark(self, bookmark: Bookmark) -> CanonicalEntity | None:
        return self.resolve_target(bookmark.subject_kind, bookmark.subject_id)
