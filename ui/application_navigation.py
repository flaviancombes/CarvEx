"""Contrôleurs Qt de navigation et de workflow Evidence.

Ils assemblent exclusivement les vues et les API publiques existantes. Aucune
logique Investigation, persistance ou résolution d'identité ne vit dans les
widgets ni dans ``MainWindow``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from PySide6.QtWidgets import QInputDialog

from bookmarks.model import Bookmark
from investigation.collection import InvestigationCollectionId
from investigation.target_ref import InvestigationTargetRef
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.context import SelectionContext
from selection.manager import SelectionManager
from selection.resolver import FileSelectionRegistry


class ApplicationNavigationController:
    """Coordonne les sélections des vues sans construire de données métier."""

    def __init__(
        self,
        selection_manager: SelectionManager,
        entity_resolver: CanonicalEntityResolver,
        files: FileSelectionRegistry,
        file_table,
        tabs,
        status_message: Callable[[str], None],
        parent,
    ) -> None:
        self._selection_manager = selection_manager
        self._entity_resolver = entity_resolver
        self._files = files
        self._file_table = file_table
        self._tabs = tabs
        self._status_message = status_message
        self._parent = parent
        self._synchronizing = False

    def open_timeline_event(self, event: object) -> None:
        """Ouvre le fichier canonique associé à l'événement Timeline."""
        resolved = self._entity_resolver.resolve(event)
        if resolved is None or not resolved.is_file or resolved.file_record is None:
            return
        self.publish_timeline_selection(event)
        self._tabs.setCurrentIndex(0)
        self._synchronizing = True
        try:
            if not self._file_table.select_record(resolved.file_record):
                event_id = getattr(event, "event_id", "")
                self._selection_manager.publish(
                    SelectionContext("file", resolved.identifier, "timeline_view", related_ids={"event_id": event_id})
                )
        finally:
            self._synchronizing = False

    def publish_timeline_selection(self, event: object, origin: str = "timeline_view") -> None:
        resolved = self._entity_resolver.resolve(event)
        if resolved is None or not resolved.is_file:
            return
        self._selection_manager.publish(
            SelectionContext(
                "file",
                resolved.identifier,
                origin,
                related_ids={"event_id": getattr(event, "event_id", "")},
            )
        )

    def publish_file_selection(self, file_record: Mapping[str, Any] | None) -> None:
        if self._synchronizing:
            return
        if file_record is None:
            self._selection_manager.clear_current()
            return
        resolved = self._entity_resolver.resolve(file_record)
        if resolved is not None and resolved.is_file:
            self._selection_manager.publish(SelectionContext("file", resolved.identifier, "files_view"))

    def publish_bookmark_selection(self, bookmark: Bookmark) -> None:
        resolved = self._entity_resolver.resolve(bookmark)
        if resolved is not None:
            self._selection_manager.publish(SelectionContext(resolved.kind, resolved.identifier, "bookmarks_view"))

    def publish_investigation_selection(self, context: SelectionContext) -> None:
        self._selection_manager.publish(context)

    def open_investigation_file_default(self, file_id: str) -> None:
        file_record = self._files.record_for(file_id)
        if file_record is None:
            self._status_message("Fichier associé introuvable dans le rapport actif.")
            return
        self._file_table.file_actions.open_file(file_record, self._parent)

    def handle_selection_navigation(self, context: SelectionContext | None) -> None:
        if context is None or context.navigation_hint.get("view") != "files" or context.subject_kind != "file":
            return
        file_record = self._files.record_for(context.subject_id)
        if file_record is None:
            self._status_message("Fichier associé introuvable dans le rapport actif.")
            return
        self._tabs.setCurrentIndex(0)
        self._synchronizing = True
        try:
            self._file_table.select_record(file_record)
        finally:
            self._synchronizing = False


class EvidenceWorkflowController:
    """Point d'entrée UI unique vers le dialogue Evidence partagé."""

    def __init__(
        self,
        entity_resolver: CanonicalEntityResolver,
        investigation_panel,
        timeline_view,
        bookmarks_view,
        tabs,
        status_message: Callable[[str], None],
        persistent_change: Callable[[], None],
        refresh_file_markers: Callable[[Iterable[str]], None] | None = None,
        parent=None,
    ) -> None:
        self._entity_resolver = entity_resolver
        self._investigation_panel = investigation_panel
        self._timeline_view = timeline_view
        self._bookmarks_view = bookmarks_view
        self._tabs = tabs
        self._status_message = status_message
        self._persistent_change = persistent_change
        self._refresh_file_markers = refresh_file_markers
        self._parent = parent

    def add_file(self, file_record: Mapping[str, Any] | None) -> None:
        if file_record is None:
            return
        resolved = self._entity_resolver.resolve(file_record)
        if resolved is None or not resolved.is_file:
            return
        self._edit(
            InvestigationTargetRef("file", resolved.identifier),
            original_name=str(file_record.get("name") or "Fichier"),
            evidence_type=str(file_record.get("mime") or file_record.get("category") or ""),
            sha256=str(file_record.get("sha256") or ""),
        )

    def add_timeline_event(self, event: object) -> None:
        resolved = self._entity_resolver.resolve(event)
        if resolved is None or not resolved.is_file or resolved.file_record is None:
            self._status_message("Cet événement Timeline n'est associé à aucun fichier importé.")
            return
        record = resolved.file_record
        event_type = getattr(getattr(event, "event_type", None), "label", "")
        self._edit(
            InvestigationTargetRef("file", resolved.identifier),
            original_name=str(record.get("name") or event_type),
            evidence_type=str(record.get("mime") or event_type),
            sha256=str(record.get("sha256") or ""),
        )

    def add_bookmark(self, bookmark: Bookmark) -> None:
        resolved = self._entity_resolver.resolve(bookmark)
        if resolved is None or not resolved.is_file:
            self._status_message("Ce bookmark n'est associé à aucun fichier importé.")
            return
        record = resolved.file_record or {}
        self._edit(
            InvestigationTargetRef("file", resolved.identifier),
            original_name=str(record.get("name") or "Fichier"),
            evidence_type=str(record.get("mime") or ""),
            sha256=str(record.get("sha256") or ""),
        )

    def file_is_in_investigation(self, file_record: Mapping[str, Any]) -> bool:
        resolved = self._entity_resolver.resolve(file_record)
        return bool(
            resolved is not None and resolved.is_file and self._investigation_panel.has_file_item(resolved.identifier)
        )

    def timeline_event_is_in_investigation(self, event: object) -> bool:
        resolved = self._entity_resolver.resolve(event)
        return bool(
            resolved is not None and resolved.is_file and self._investigation_panel.has_file_item(resolved.identifier)
        )

    def bookmark_is_in_investigation(self, bookmark: Bookmark) -> bool:
        resolved = self._entity_resolver.resolve(bookmark)
        return bool(
            resolved is not None and resolved.is_file and self._investigation_panel.has_file_item(resolved.identifier)
        )

    def add_files_bulk(self, file_ids: Iterable[str]) -> None:
        """Commande UI unique : création groupée des preuves sélectionnées."""
        identifiers = tuple(dict.fromkeys(file_id for file_id in file_ids if file_id))
        if not identifiers:
            return
        service = self._investigation_panel.service
        if service is None:
            return
        result = service.create_items_batch(tuple(InvestigationTargetRef("file", file_id) for file_id in identifiers))
        self._after_bulk_change(identifiers, result.applied_count, "preuve(s) ajoutée(s) à Investigation.")

    def add_files_to_collection_bulk(self, file_ids: Iterable[str]) -> None:
        """Choisit une Collection, puis exécute une unique commande de masse."""
        identifiers = tuple(dict.fromkeys(file_id for file_id in file_ids if file_id))
        if not identifiers:
            return
        service = self._investigation_panel.service
        if service is None:
            return
        collections = service.list_collections()
        if not collections:
            self._status_message("Créez d'abord une Collection avant d'y ajouter des fichiers.")
            return
        labels = [collection.title for collection in collections]
        selected, accepted = QInputDialog.getItem(
            self._parent,
            "Ajouter à une Collection",
            "Collection :",
            labels,
            0,
            False,
        )
        if not accepted:
            return
        collection = next(collection for collection in collections if collection.title == selected)
        result = service.add_files_to_collection_batch(
            InvestigationCollectionId(str(collection.collection_id)), identifiers
        )
        self._after_bulk_change(identifiers, result.applied_count, "fichier(s) ajouté(s) à la Collection.")

    def _after_bulk_change(self, file_ids: tuple[str, ...], applied_count: int, message: str) -> None:
        if self._refresh_file_markers is not None:
            self._refresh_file_markers(file_ids)
        self._timeline_view.set_investigation_presence_lookup(self.timeline_event_is_in_investigation)
        self._bookmarks_view.set_investigation_presence_lookup(self.bookmark_is_in_investigation)
        self._persistent_change()
        self._status_message(f"{applied_count} {message}")

    def _edit(
        self,
        target: InvestigationTargetRef,
        *,
        original_name: str,
        evidence_type: str = "",
        sha256: str = "",
    ) -> None:
        item = self._investigation_panel.edit_evidence(
            target,
            original_name=original_name,
            evidence_type=evidence_type,
            sha256=sha256,
        )
        if item is None:
            return
        self._tabs.setCurrentIndex(3)
        self._timeline_view.set_investigation_presence_lookup(self.timeline_event_is_in_investigation)
        self._bookmarks_view.set_investigation_presence_lookup(self.bookmark_is_in_investigation)
        self._persistent_change()
        self._status_message("Preuve enregistrée dans Investigation.")
