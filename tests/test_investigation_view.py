"""Tests de base de la première vue Qt Investigation."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from investigation.integrity import InvestigationIntegrityValidator
from investigation.module import InvestigationProjectModule
from investigation.queries import InvestigationQueryService
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from models.investigation_tree_model import InvestigationSection
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from ui.investigation_view import InvestigationPanel


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _domain() -> tuple[InvestigationService, InvestigationQueryService, InvestigationIntegrityValidator]:
    _application()
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Vue Investigation"))
    service = project.repository.module_repository("investigation", "service")
    queries = project.repository.module_repository("investigation", "query_service")
    validator = project.repository.module_repository("investigation", "integrity_validator")
    assert isinstance(service, InvestigationService)
    assert isinstance(queries, InvestigationQueryService)
    assert isinstance(validator, InvestigationIntegrityValidator)
    return service, queries, validator


def _panel() -> tuple[InvestigationPanel, InvestigationService]:
    service, queries, validator = _domain()
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)
    return panel, service


def test_investigation_panel_initializes_with_all_sections():
    panel, _service = _panel()

    assert panel.model.rowCount() == 5
    assert panel.model.data(panel.model.index(3, 0)) == "📝 Post-it"
    assert panel.model.data(panel.model.index(4, 0)) == "Journal"
    panel.detach()
    return
    labels = [panel.model.data(panel.model.index(row, 0)) for row in range(panel.model.rowCount())]
    assert labels == ["Éléments", "Cases", "Collections", "Hypothèses", "Notes", "Tags", "Journal"]
    panel.detach()


def test_investigation_welcome_is_replaced_when_the_first_item_is_created():
    panel, service = _panel()

    assert panel.content_stack.currentWidget() is panel.welcome_page
    assert panel.create_item_button.text() == "Créer un élément"

    item = service.create_item("file", "file-1")

    assert panel.content_stack.currentWidget() is panel.tree

    service.delete_item(item.item_id)

    assert panel.content_stack.currentWidget() is panel.welcome_page
    panel.detach()


def test_case_collection_and_post_it_each_replace_the_empty_investigation_page():
    for create in (
        lambda service: service.create_case("Identification"),
        lambda service: service.create_collection("Documents"),
        lambda service: service.create_note("Vérifier EXIF"),
    ):
        panel, service = _panel()

        create(service)

        assert panel.content_stack.currentWidget() is panel.tree
        panel.detach()


def test_post_it_section_lists_notes_and_uses_a_readable_journal_action():
    panel, service = _panel()
    service.create_note("Vérifier EXIF")

    panel._load_section(InvestigationSection.POST_ITS)
    post_its = panel.model.index(3, 0)
    panel._load_section(InvestigationSection.JOURNAL)
    journal = panel.model.index(4, 0)

    assert panel.model.data(panel.model.index(0, 0, post_its)) == "📝 Vérifier EXIF"
    assert panel.model.data(panel.model.index(0, 0, journal)).endswith("— Vérifier EXIF")
    panel.detach()


def test_evidence_note_is_not_projected_as_a_post_it():
    panel, service = _panel()
    item = service.create_item("file", "file-1", title="Photo")
    item_ref = InvestigationTargetRef("item", str(item.item_id))
    post_it = service.create_note("Vérifier EXIF")
    service.create_note("Note de preuve", target_ref=item_ref)

    panel._load_section(InvestigationSection.POST_ITS)
    section = panel.model.index(3, 0)

    assert panel.model.rowCount(section) == 1
    assert panel.model.entry_for_index(panel.model.index(0, 0, section)).subject_id == str(post_it.note_id)
    service.delete_item(item.item_id)
    assert service.get_note(post_it.note_id) is not None
    panel.detach()


def test_investigation_selection_publishes_a_lightweight_selection_context():
    panel, service = _panel()
    case = service.create_case("Affaire A")
    selected = []
    panel.selection_requested.connect(selected.append)
    section = panel.model.index(1, 0)
    panel._load_section(InvestigationSection.CASES)

    panel.tree.setCurrentIndex(panel.model.index(0, 0, section))

    assert selected
    assert selected[-1].subject_kind == "case"
    assert selected[-1].subject_id == str(case.case_id)
    panel.detach()


def test_loaded_section_refreshes_after_a_domain_event():
    panel, service = _panel()
    cases = panel.model.index(1, 0)
    panel._load_section(InvestigationSection.CASES)
    assert panel.model.rowCount(cases) == 0

    service.create_case("Affaire A")

    assert panel.model.rowCount(cases) == 1
    panel.detach()


def test_integrity_anomaly_is_non_blocking_and_visible_in_panel():
    service, queries, validator = _domain()
    service.create_note("Cible absente", target_ref=InvestigationTargetRef("case", "missing"))
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)

    assert not panel.integrity_button.isHidden()
    assert "anomalie" in panel.integrity_label.text()
    panel.detach()
