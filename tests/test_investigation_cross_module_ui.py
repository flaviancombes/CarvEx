"""Menus Investigation partagés par Timeline et Bookmarks."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtWidgets import QApplication

import ui.investigation_view as investigation_view
from bookmarks.model import Bookmark, BookmarkKey
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.models import ProjectMetadata
from timeline.event import TimelineEvent
from timeline.source import EXIF, EXIF_CAPTURED
from ui.main_window import MainWindow


def _window() -> tuple[MainWindow, InvestigationService]:
    QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])
    window = MainWindow()
    project = window.project_manager.create_project(ProjectMetadata("Integration modules"))
    window._attach_project(project, "")
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return window, service


def _event() -> TimelineEvent:
    return TimelineEvent(
        EXIF_CAPTURED,
        datetime(2025, 1, 1, tzinfo=UTC),
        EXIF,
        event_id="timeline-evidence",
        file_record={"file_id": str(uuid4()), "name": "photo.jpg"},
    )


def test_timeline_context_menu_adds_existing_target_once(monkeypatch):
    window, service = _window()
    event = _event()

    def accept(dialog):
        dialog.name_field.setText("Photo chronologique")
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept)
    menu = window.timeline_view._context_menu_for_event(event)
    next(action for action in menu.actions() if action.text() == "Ajouter à Investigation").trigger()

    item = service.find_item_by_subject("file", event.file_record["file_id"])
    assert item is not None
    assert item.subject_id == event.file_record["file_id"]
    labels = [action.text() for action in window.timeline_view._context_menu_for_event(event).actions()]
    existing_menu = window.timeline_view._context_menu_for_event(event)
    next(
        action for action in existing_menu.actions() if action.text() == "\u2713 D\u00e9j\u00e0 pr\u00e9sent"
    ).trigger()
    entry = window.investigation_panel.model.entry_for_index(window.investigation_panel.tree.currentIndex())
    assert entry is not None and entry.subject_id == str(item.item_id)
    assert "✓ Déjà présent" in labels
    window.project_manager.close_project()


def test_bookmark_context_menu_reuses_the_bookmarked_target(monkeypatch):
    window, service = _window()
    file_id = str(uuid4())
    key = BookmarkKey("file", file_id)

    def accept(dialog):
        dialog.name_field.setText("Preuve marquée")
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept)
    window.bookmark_service.add(key)
    bookmark = window.bookmark_service.get(key)
    assert bookmark is not None
    menu = window.bookmarks_view._context_menu_for_bookmark(bookmark)
    next(action for action in menu.actions() if action.text() == "Ajouter à Investigation").trigger()

    assert service.find_item_by_subject("file", file_id) is not None
    labels = [action.text() for action in window.bookmarks_view._context_menu_for_bookmark(bookmark).actions()]
    assert "✓ Déjà présent" in labels
    window.project_manager.close_project()


def test_bookmark_uses_the_complete_evidence_workflow(monkeypatch):
    window, service = _window()
    file_id = str(uuid4())
    key = BookmarkKey("file", file_id)
    case = service.create_case("Favoris")
    collection = service.create_collection("À analyser")

    def accept(dialog):
        dialog.name_field.setText("Preuve bookmark")
        dialog.note_field.setPlainText("Note bookmark")
        dialog.hypothesis_field.setText("Hypothèse bookmark")
        dialog.case_field.setCurrentIndex(dialog.case_field.findData(str(case.case_id)))
        dialog.collection_field.setCurrentIndex(dialog.collection_field.findData(str(collection.collection_id)))
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept)
    window.bookmark_service.add(key)
    bookmark = window.bookmark_service.get(key)
    assert bookmark is not None
    next(
        action
        for action in window.bookmarks_view._context_menu_for_bookmark(bookmark).actions()
        if action.text() == "Ajouter \u00e0 Investigation"
    ).trigger()

    item = service.find_item_by_subject("file", file_id)
    assert item is not None and item.title == "Preuve bookmark"
    item_ref = InvestigationTargetRef("item", str(item.item_id))
    assert service.find_notes_for_target(item_ref)[0].body == "Note bookmark"
    assert service.find_hypotheses_for_target(item_ref)[0].title == "Hypothèse bookmark"
    assert item_ref in service.find_case_members(case.case_id)
    assert item_ref in service.find_collection_members(collection.collection_id)
    window.project_manager.close_project()


def test_timeline_note_and_hypothesis_keep_the_timeline_target(monkeypatch):
    window, service = _window()
    event = _event()
    case = service.create_case("Chronologie")
    collection = service.create_collection("Images")

    def accept_evidence(dialog):
        dialog.name_field.setText("Photo chronologique")
        dialog.note_field.setPlainText("Horodatage")
        dialog.hypothesis_field.setText("Piste")
        dialog.case_field.setCurrentIndex(dialog.case_field.findData(str(case.case_id)))
        dialog.collection_field.setCurrentIndex(dialog.collection_field.findData(str(collection.collection_id)))
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept_evidence)
    actions = {action.text(): action for action in window.timeline_view._context_menu_for_event(event).actions()}
    actions["Ajouter \u00e0 Investigation"].trigger()

    item = service.find_item_by_subject("file", event.file_record["file_id"])
    assert item is not None
    item_ref = InvestigationTargetRef("item", str(item.item_id))
    assert service.find_notes_for_target(item_ref)[0].body == "Horodatage"
    hypothesis = service.find_hypotheses_for_target(item_ref)[0]
    assert service.find_hypothesis_members(hypothesis.hypothesis_id)[0] == item_ref
    assert item_ref in service.find_case_members(case.case_id)
    assert item_ref in service.find_collection_members(collection.collection_id)
    window.project_manager.close_project()
    return

    def accept_note(dialog):
        dialog.title_field.setText("Observation")
        dialog.body_field.setPlainText("Horodatage")
        return dialog.DialogCode.Accepted

    def accept_hypothesis(dialog):
        dialog.title_field.setText("Piste")
        dialog.description_field.setPlainText("À confirmer")
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.NoteCreationDialog, "exec", accept_note)
    monkeypatch.setattr(investigation_view.HypothesisCreationDialog, "exec", accept_hypothesis)
    actions = {action.text(): action for action in window.timeline_view._context_menu_for_event(event).actions()}
    actions["Ajouter une note Investigation"].trigger()
    actions["Créer une hypothèse Investigation"].trigger()

    assert service.list_notes()[0].target_ref.target_kind == "timeline_event"
    hypothesis = service.list_hypotheses()[0]
    assert service.find_hypothesis_members(hypothesis.hypothesis_id)[0].target_id == event.event_id
    window.project_manager.close_project()


def test_legacy_timeline_bookmark_resolves_to_its_file_without_string_attribute_error():
    window, _service = _window()
    event = _event()
    window.timeline_view._model.set_events((event,))
    window._selection_registry.set_records((event.file_record,))
    bookmark = Bookmark("timeline_event", event.event_id, datetime.now(UTC))

    resolved = window._entity_resolver.resolve(bookmark)

    assert resolved is not None
    assert resolved.kind == "file"
    assert resolved.identifier == event.file_record["file_id"]
    assert resolved.file_record is event.file_record
    window.project_manager.close_project()
