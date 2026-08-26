"""Workflow Qt unifié d'ajout d'une preuve à Investigation."""

from __future__ import annotations

from uuid import uuid4

from PySide6.QtWidgets import QApplication

import ui.investigation_view as investigation_view
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.models import ProjectMetadata
from project.storage import JsonProjectStorage
from ui.main_window import MainWindow


def _window(storage=None) -> tuple[MainWindow, dict[str, object], InvestigationService]:
    QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])
    window = MainWindow()
    project = window.project_manager.create_project(ProjectMetadata("Preuves UX"), storage)
    window._attach_project(project, "")
    record = {
        "file_id": str(uuid4()),
        "name": "original.jpg",
        "mime": "image/jpeg",
        "sha256": "a" * 64,
    }
    window.file_table.set_files((record,))
    window._selection_registry.set_records((record,))
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return window, record, service


def _accept_evidence(monkeypatch, **values):
    def accept(dialog):
        dialog.name_field.setText(values.get("name", "Preuve affichée"))
        dialog.note_field.setPlainText(values.get("note", ""))
        dialog.hypothesis_field.setText(values.get("hypothesis", ""))
        for field_name, identifier in (
            ("case_field", values.get("case_id")),
            ("collection_field", values.get("collection_id")),
        ):
            if identifier:
                getattr(dialog, field_name).setCurrentIndex(getattr(dialog, field_name).findData(identifier))
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept)


def _item_ref(service: InvestigationService, record: dict[str, object]) -> InvestigationTargetRef:
    item = service.find_item_by_subject("file", str(record["file_id"]))
    assert item is not None
    return InvestigationTargetRef("item", str(item.item_id))


def test_complete_evidence_creation_links_every_selected_context(monkeypatch):
    window, record, service = _window()
    case = service.create_case("Suppression")
    collection = service.create_collection("À inclure")
    _accept_evidence(
        monkeypatch,
        name="Photo de référence",
        note="GPS à confirmer",
        hypothesis="La photo a été supprimée",
        case_id=str(case.case_id),
        collection_id=str(collection.collection_id),
    )

    window._add_file_to_investigation(record)

    item_ref = _item_ref(service, record)
    item = service.find_item_by_subject("file", str(record["file_id"]))
    assert item is not None and item.title == "Photo de référence"
    assert service.find_notes_for_target(item_ref)[0].body == "GPS à confirmer"
    hypothesis = service.find_hypotheses_for_target(item_ref)[0]
    assert hypothesis.title == "La photo a été supprimée"
    assert item_ref in service.find_case_members(case.case_id)
    assert item_ref in service.find_collection_members(collection.collection_id)
    assert window.main_tabs.currentIndex() == 3
    assert window.investigation_panel.tree.currentIndex().isValid()
    evidence_widget = window.details_panel._file_extension_widget
    assert evidence_widget is not None
    assert not evidence_widget.evidence_note_group.isHidden()
    assert not evidence_widget.evidence_hypothesis_group.isHidden()
    assert window.details_panel.content_layout.indexOf(evidence_widget) < window.details_panel.content_layout.indexOf(
        window.details_panel.preview_panel.parentWidget()
    )


def test_evidence_creation_accepts_each_optional_context_independently(monkeypatch):
    options = (
        {"name": "Nom seulement"},
        {"name": "Avec note", "note": "Observation"},
        {"name": "Avec hypothèse", "hypothesis": "Piste"},
    )
    for _index, values in enumerate(options):
        window, record, service = _window()
        record["file_id"] = str(uuid4())
        _accept_evidence(monkeypatch, **values)
        window._add_file_to_investigation(record)
        item_ref = _item_ref(service, record)
        assert service.find_item_by_subject("file", str(record["file_id"])).title == values["name"]
        assert bool(service.find_notes_for_target(item_ref)) is ("note" in values)
        assert bool(service.find_hypotheses_for_target(item_ref)) is ("hypothesis" in values)
        window.project_manager.close_project()


def test_existing_evidence_is_updated_without_creating_a_duplicate(monkeypatch):
    window, record, service = _window()
    _accept_evidence(monkeypatch, name="Version initiale", note="Note initiale", hypothesis="Piste initiale")
    window._add_file_to_investigation(record)

    def accept_existing(dialog):
        assert not dialog.presence_label.isHidden()
        assert dialog.name_field.text() == "Version initiale"
        assert dialog.note_field.toPlainText() == "Note initiale"
        assert dialog.hypothesis_field.text() == "Piste initiale"
        dialog.name_field.setText("Version révisée")
        dialog.note_field.setPlainText("Note révisée")
        dialog.hypothesis_field.setText("Piste révisée")
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.EvidenceDialog, "exec", accept_existing)
    window._add_file_to_investigation(record)

    item_ref = _item_ref(service, record)
    item = service.find_item_by_subject("file", str(record["file_id"]))
    assert item is not None and item.title == "Version révisée"
    assert len(service.list_items()) == 1
    assert len(service.find_notes_for_target(item_ref)) == 1
    assert service.find_notes_for_target(item_ref)[0].body == "Note révisée"
    assert len(service.find_hypotheses_for_target(item_ref)) == 1
    assert service.find_hypotheses_for_target(item_ref)[0].title == "Piste révisée"


def test_evidence_case_and_collection_selection_are_persisted(monkeypatch, tmp_path):
    root = tmp_path / "evidence.carvex"
    window, record, service = _window(JsonProjectStorage(root, create=True))
    case = service.create_case("Case")
    collection = service.create_collection("Collection")
    _accept_evidence(
        monkeypatch, name="Persistée", case_id=str(case.case_id), collection_id=str(collection.collection_id)
    )
    window._add_file_to_investigation(record)
    window.project_manager.save_project()
    window.project_manager.close_project()

    reopened = MainWindow()
    project = reopened.project_manager.open_project(root)
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    item = service.find_item_by_subject("file", str(record["file_id"]))
    assert item is not None and item.title == "Persistée"
    item_ref = InvestigationTargetRef("item", str(item.item_id))
    assert item_ref in service.find_case_members(case.case_id)
    assert item_ref in service.find_collection_members(collection.collection_id)
