"""Consultation, édition et suppression via le provider DetailsPanel Investigation."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

from investigation.hypothesis import HypothesisRole
from investigation.integrity import InvestigationIntegrityValidator
from investigation.module import InvestigationProjectModule
from investigation.queries import InvestigationQueryService
from investigation.relation import InvestigationRelationType
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from selection.context import SelectionContext
from ui.investigation_details_provider import InvestigationDetailsProvider
from ui.investigation_dialogs import ItemCreationDialog, NoteCreationDialog
from ui.investigation_view import InvestigationPanel
from ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _domain() -> tuple[InvestigationService, InvestigationQueryService, InvestigationIntegrityValidator]:
    _application()
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Details Investigation"))
    service = project.repository.module_repository("investigation", "service")
    queries = project.repository.module_repository("investigation", "query_service")
    validator = project.repository.module_repository("investigation", "integrity_validator")
    assert isinstance(service, InvestigationService)
    assert isinstance(queries, InvestigationQueryService)
    assert isinstance(validator, InvestigationIntegrityValidator)
    return service, queries, validator


class _Panel:
    def __init__(self) -> None:
        self._content = QWidget()
        self.title = ""
        self.provider_widget = None
        self.cleared = False
        self.published = []

    def show_provider_widget(self, title, widget) -> None:
        self.title = title
        self.provider_widget = widget

    def clear_provider_widget(self) -> None:
        self.cleared = True

    def widget(self):
        return self._content

    def publish_context(self, context) -> None:
        self.published.append(context)


def test_provider_displays_and_updates_an_investigation_item():
    service, _queries, _validator = _domain()
    item = service.create_item("photo", "manual-1", title="Initial", summary="Avant")
    provider = InvestigationDetailsProvider(service)
    panel = _Panel()

    provider.populate(panel, SelectionContext("item", str(item.item_id), "test"))

    assert panel.title == "Élément Investigation"
    assert panel.provider_widget.name_field.text() == "Initial"
    assert panel.provider_widget.description_field.toPlainText() == "Avant"
    assert panel.provider_widget.type_field.text() == "photo"

    panel.provider_widget.name_field.setText("Modifié")
    panel.provider_widget.description_field.setPlainText("Après")
    panel.provider_widget.save_button.click()

    updated = service.get_item(item.item_id)
    assert updated is not None
    assert updated.title == "Modifié"
    assert updated.summary == "Après"


def test_investigation_item_name_remains_copyable_as_plain_text():
    app = _application()
    service, _queries, _validator = _domain()
    item = service.create_item("file", "file-1", title="f3561792.jpg")
    provider = InvestigationDetailsProvider(service)
    panel = _Panel()

    provider.populate(panel, SelectionContext("item", str(item.item_id), "test"))
    panel.provider_widget.name_field.selectAll()
    panel.provider_widget.name_field.copy()

    assert app.clipboard().text() == "f3561792.jpg"


def test_provider_deletes_only_after_confirmation(monkeypatch):
    service, _queries, _validator = _domain()
    case = service.create_case("À supprimer")
    provider = InvestigationDetailsProvider(service)
    panel = _Panel()
    provider.populate(panel, SelectionContext("case", str(case.case_id), "test"))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)

    panel.provider_widget.delete_button.click()

    assert service.get_case(case.case_id) is None
    assert panel.cleared


def test_provider_displays_note_hypothesis_and_collection_properties():
    service, _queries, _validator = _domain()
    note = service.create_note("Titre note\n\nContenu note")
    hypothesis = service.create_hypothesis("Piste", description="À vérifier")
    collection = service.create_collection("Éléments importants", description="Sélection")
    provider = InvestigationDetailsProvider(service)
    panel = _Panel()

    provider.populate(panel, SelectionContext("note", str(note.note_id), "test"))
    assert panel.provider_widget.description_field.toPlainText() == "Titre note"
    assert panel.provider_widget.content_field.toPlainText() == "Contenu note"

    provider.populate(panel, SelectionContext("hypothesis", str(hypothesis.hypothesis_id), "test"))
    assert panel.provider_widget.name_field.text() == "Piste"
    assert panel.provider_widget.description_field.toPlainText() == "À vérifier"

    provider.populate(panel, SelectionContext("collection", str(collection.collection_id), "test"))
    assert panel.provider_widget.name_field.text() == "Éléments importants"
    assert panel.provider_widget.description_field.toPlainText() == "Sélection"


def test_panel_selection_populates_properties_through_the_existing_controller():
    service, queries, validator = _domain()
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)
    service.create_case("Affaire visible", description="Description visible")
    selected = []
    panel.selection_requested.connect(selected.append)
    panel._load_section(panel.model.index(1, 0).internalPointer())

    panel.tree.setCurrentIndex(panel.model.index(0, 0, panel.model.index(1, 0)))

    assert selected[-1].subject_kind == "case"
    panel.detach()


def test_main_window_details_panel_adapts_to_an_investigation_selection():
    _application()
    window = MainWindow()
    project = window.project_manager.create_project(ProjectMetadata("Panneau partagé"))
    window._attach_project(project, "")
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    service.create_case("Affaire visible", description="Description visible")
    cases = window.investigation_panel.model.index(1, 0)

    window.investigation_panel.tree.setCurrentIndex(window.investigation_panel.model.index(0, 0, cases))

    widget = window.details_panel._provider_widget
    assert widget is not None
    assert window.details_panel.title.text() == "Case Investigation"
    assert widget.name_field.text() == "Affaire visible"
    assert widget.description_field.toPlainText() == "Description visible"
    window.investigation_panel.detach()
    window.project_manager.close_project()


def test_creation_dialogs_explain_missing_required_values():
    _application()
    item = ItemCreationDialog()
    note = NoteCreationDialog()

    item._accept_if_valid()
    note._accept_if_valid()

    assert "requis" in item.error_label.text()
    assert "requis" in note.error_label.text()


def test_note_attachment_and_hypothesis_context_are_projected_and_navigable():
    service, _queries, _validator = _domain()
    item = service.create_item("file", "file-1", title="Preuve")
    item_ref = InvestigationTargetRef("item", str(item.item_id))
    note = service.create_note("Note liée", target_ref=item_ref)
    hypothesis = service.create_hypothesis("Piste")
    hypothesis_ref = InvestigationTargetRef("hypothesis", str(hypothesis.hypothesis_id))
    service.add_to_hypothesis(hypothesis.hypothesis_id, item_ref, HypothesisRole.SUPPORTS)
    service.add_to_hypothesis(
        hypothesis.hypothesis_id, InvestigationTargetRef("note", str(note.note_id)), HypothesisRole.OBSERVATION
    )
    service.create_relation(hypothesis_ref, item_ref, InvestigationRelationType.CONFIRMS)
    provider = InvestigationDetailsProvider(service)
    panel = _Panel()

    provider.populate(panel, SelectionContext("note", str(note.note_id), "test"))
    attachment = next(
        button for button in panel.provider_widget.attachment_group.findChildren(QWidget) if hasattr(button, "click")
    )
    attachment.click()
    assert panel.published[-1].subject_kind == "item"
    assert panel.published[-1].subject_id == str(item.item_id)

    provider.populate(panel, SelectionContext("hypothesis", str(hypothesis.hypothesis_id), "test"))
    widget = panel.provider_widget
    assert "Nombre de preuves : 2" in widget.hypothesis_statistics.text()
    assert "Nombre de notes : 1" in widget.hypothesis_statistics.text()
    evidence_buttons = widget.hypothesis_evidence_group.findChildren(QPushButton)
    next(button for button in evidence_buttons if "supports" in button.text()).click()
    assert panel.published[-1].subject_kind == "item"
    assert panel.published[-1].subject_id == str(item.item_id)
    assert widget.journal_group.findChildren(QWidget)
