"""Création Qt des entités Investigation via la façade publique."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

import ui.investigation_view as investigation_view
from investigation.integrity import InvestigationIntegrityValidator
from investigation.module import InvestigationProjectModule
from investigation.queries import InvestigationQueryService
from investigation.service import InvestigationService
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from ui.investigation_dialogs import (
    CaseCreationDialog,
    CollectionCreationDialog,
    EvidenceDialog,
    HypothesisCreationDialog,
    ItemCreationDialog,
    NoteCreationDialog,
)
from ui.investigation_view import InvestigationPanel


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _panel() -> tuple[InvestigationPanel, InvestigationService]:
    _application()
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Création UI"))
    service = project.repository.module_repository("investigation", "service")
    queries = project.repository.module_repository("investigation", "query_service")
    validator = project.repository.module_repository("investigation", "integrity_validator")
    assert isinstance(service, InvestigationService)
    assert isinstance(queries, InvestigationQueryService)
    assert isinstance(validator, InvestigationIntegrityValidator)
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)
    return panel, service


def _accept_item(dialog):
    dialog.name_field.setText("Photo notable")
    dialog.description_field.setPlainText("À confirmer")
    dialog.type_field.setText("photo")
    return dialog.DialogCode.Accepted


def _accept_note(dialog):
    dialog.title_field.setText("Observation")
    dialog.body_field.setPlainText("Contenu de la note")
    return dialog.DialogCode.Accepted


def _accept_hypothesis(dialog):
    dialog.title_field.setText("Piste USB")
    dialog.description_field.setPlainText("Hypothèse initiale")
    dialog.confidence_field.setCurrentIndex(2)
    dialog.status_field.setCurrentIndex(1)
    return dialog.DialogCode.Accepted


def _accept_named(dialog):
    dialog.name_field.setText("Affaire A")
    dialog.description_field.setPlainText("Description")
    return dialog.DialogCode.Accepted


def _selected_kind(panel: InvestigationPanel) -> str:
    entry = panel.model.entry_for_index(panel.tree.currentIndex())
    assert entry is not None
    return entry.subject_kind


def test_creation_dialogs_expose_the_expected_fields():
    _application()

    assert ItemCreationDialog().name_field is not None
    assert ItemCreationDialog().type_field is not None
    assert NoteCreationDialog().title_field is not None
    assert NoteCreationDialog().body_field is not None
    assert HypothesisCreationDialog().confidence_field.count() == 3
    assert HypothesisCreationDialog().status_field.count() == 4
    assert CaseCreationDialog().description_field is not None
    assert CollectionCreationDialog().description_field is not None


def test_evidence_dialog_selects_a_newly_created_case_and_collection():
    dialog = EvidenceDialog(
        display_name="Preuve",
        original_name="preuve.jpg",
        evidence_type="image/jpeg",
        sha256="",
        note="",
        hypothesis="",
        cases=(),
        collections=(),
    )

    dialog.add_case("Identification", "case-1")
    dialog.add_collection("Documents", "collection-1")

    assert dialog.case_field.currentData() == "case-1"
    assert dialog.collection_field.currentData() == "collection-1"


def test_item_button_creates_refreshes_selects_and_hides_welcome(monkeypatch):
    panel, service = _panel()
    monkeypatch.setattr(investigation_view.ItemCreationDialog, "exec", _accept_item)

    panel.create_item_button.click()

    assert service.list_items()[0].title == "Photo notable"
    assert panel.content_stack.currentWidget() is panel.tree
    assert _selected_kind(panel) == "item"
    panel.detach()


def test_note_is_not_exposed_as_a_top_level_action(monkeypatch):
    panel, service = _panel()
    assert not hasattr(panel, "create_note_button")
    panel.detach()


def test_hypothesis_is_not_exposed_as_a_top_level_action(monkeypatch):
    panel, service = _panel()
    assert not hasattr(panel, "create_hypothesis_button")
    panel.detach()


def test_post_it_is_created_from_the_global_investigation_bar(monkeypatch):
    panel, service = _panel()
    monkeypatch.setattr(investigation_view.NoteCreationDialog, "exec", _accept_note)

    panel.create_post_it_button.click()

    assert len(service.list_notes()) == 1
    assert service.list_notes()[0].target_ref is None
    panel.detach()


def test_case_and_collection_buttons_create_refresh_and_select(monkeypatch):
    panel, service = _panel()
    monkeypatch.setattr(investigation_view.CaseCreationDialog, "exec", _accept_named)
    monkeypatch.setattr(investigation_view.CollectionCreationDialog, "exec", _accept_named)

    panel.create_case_button.click()

    assert service.list_cases()[0].title == "Affaire A"
    assert _selected_kind(panel) == "case"

    panel.create_collection_button.click()

    assert service.list_collections()[0].title == "Affaire A"
    assert _selected_kind(panel) == "collection"
    panel.detach()
