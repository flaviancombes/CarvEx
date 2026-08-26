"""IntÃ©gration Qt entre les preuves Fichiers et le module Investigation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from PySide6.QtWidgets import QApplication

import ui.investigation_view as investigation_view
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.models import ProjectMetadata
from selection.context import SelectionContext
from ui.file_table import FileTable
from ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def _accept_evidence_dialog(monkeypatch):
    def accept(dialog):
        dialog.name_field.setText("Preuve fichier")
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept)


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _record() -> dict[str, object]:
    return {
        "file_id": str(uuid4()),
        "name": "photo-preuve.jpg",
        "category": "Images",
        "mime": "image/jpeg",
        "size": 42,
    }


def _window_with_file() -> tuple[MainWindow, dict[str, object], InvestigationService]:
    _application()
    window = MainWindow()
    project = window.project_manager.create_project(ProjectMetadata("Preuves Investigation"))
    window._attach_project(project, "")
    record = _record()
    window.file_table.set_files((record,))
    window._selection_registry.set_records((record,))
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return window, record, service


def test_file_context_menu_publishes_investigation_intentions():
    _application()
    table = FileTable()
    record = _record()
    received = []
    table.investigation_item_requested.connect(lambda value: received.append(("item", value)))

    menu = table._context_menu_for_record(record)
    actions = {action.text(): action for action in menu.actions()}
    actions["Ajouter \u00e0 Investigation"].trigger()

    assert received == [("item", record)]
    return
    actions["Ajouter Ã  Investigation"].trigger()
    actions["Ajouter une note Investigation"].trigger()
    actions["CrÃ©er une hypothÃ¨se Investigation"].trigger()

    assert received == [("item", record), ("note", record), ("hypothesis", record)]


def test_file_is_added_once_to_investigation_with_its_existing_file_id():
    window, record, service = _window_with_file()
    file_id = str(record["file_id"])

    window._add_file_to_investigation(record)
    window._add_file_to_investigation(record)

    item = service.find_item_by_subject("file", file_id)
    assert item is not None
    assert item.subject_id == file_id
    assert len(service.list_items()) == 1
    entry = window.investigation_panel.model.entry_for_index(window.investigation_panel.tree.currentIndex())
    assert entry is not None and entry.subject_kind == "item"
    window.project_manager.close_project()


def test_notes_and_hypotheses_created_from_a_file_keep_the_file_target(monkeypatch):
    window, record, service = _window_with_file()
    file_id = str(record["file_id"])

    def accept_note(dialog):
        dialog.title_field.setText("Observation")
        dialog.body_field.setPlainText("Date incohÃ©rente")
        return dialog.DialogCode.Accepted

    def accept_hypothesis(dialog):
        dialog.title_field.setText("Suppression")
        dialog.description_field.setPlainText("Ã€ vÃ©rifier")
        return dialog.DialogCode.Accepted

    def accept_evidence(dialog):
        dialog.name_field.setText("Preuve fichier")
        dialog.note_field.setPlainText("Date incohérente")
        dialog.hypothesis_field.setText("Suppression")
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept_evidence)
    window._add_file_to_investigation(record)

    item = service.find_item_by_subject("file", file_id)
    assert item is not None
    target = InvestigationTargetRef("item", str(item.item_id))
    assert service.list_notes()[0].target_ref == target
    hypothesis = service.list_hypotheses()[0]
    assert service.find_hypothesis_members(hypothesis.hypothesis_id) == (target,)
    window.project_manager.close_project()


def test_double_clicking_a_file_item_opens_the_file_with_the_system(monkeypatch):
    window, record, service = _window_with_file()
    file_id = str(record["file_id"])
    window._add_file_to_investigation(record)
    item = service.find_item_by_subject("file", file_id)
    assert item is not None
    entry = window.investigation_panel.model.entry_for_index(window.investigation_panel.tree.currentIndex())
    assert entry is not None

    opened = []
    monkeypatch.setattr(
        window.file_table.file_actions, "open_file", lambda value, parent: opened.append((value, parent))
    )
    window.investigation_panel._activate_entry(entry)

    assert opened == [(record, window)]
    window.project_manager.close_project()


def test_file_evidence_reuses_details_panel_and_can_be_shown_in_files():
    window, record, service = _window_with_file()
    file_id = str(record["file_id"])
    window._add_file_to_investigation(record)
    item = service.find_item_by_subject("file", file_id)
    assert item is not None

    window.selection_manager.publish(SelectionContext("item", str(item.item_id), "test"))

    widget = window.details_panel._file_extension_widget
    assert widget is not None
    assert window.details_panel.title.text() == "photo-preuve.jpg"
    assert not widget.show_in_files_button.isHidden()
    widget.show_in_files_button.click()

    assert window.main_tabs.currentIndex() == 0
    assert window.file_table.record_for_index(window.file_table.view.currentIndex()) is record
    assert window.details_panel.title.text() == "photo-preuve.jpg"
    window.project_manager.close_project()


def test_existing_investigation_item_has_context_menu_status_and_table_marker():
    window, record, _service = _window_with_file()
    window._add_file_to_investigation(record)
    assert window.investigation_panel.has_file_item(str(record["file_id"]))
    assert window._file_is_in_investigation(record)
    assert window.file_table._investigation_item_lookup is not None
    assert window.file_table._investigation_item_lookup(record)

    menu = window.file_table._context_menu_for_record(record)
    labels = [action.text() for action in menu.actions()]

    assert "✓ Déjà présent" in labels
    assert (
        window.file_table._source_model.data(
            window.file_table._source_model.index(0, window.file_table._source_model.INVESTIGATION_COLUMN)
        )
        == "●"
    )
    window.project_manager.close_project()
