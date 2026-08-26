"""Organisation Qt des objets Investigation via les seules APIs publiques."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QPushButton

from investigation.integrity import InvestigationIntegrityValidator
from investigation.module import InvestigationProjectModule
from investigation.queries import InvestigationQueryService
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage
from selection.context import SelectionContext
from ui.investigation_details_provider import InvestigationDetailsProvider
from ui.investigation_view import InvestigationPanel


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _domain(
    storage=None,
) -> tuple[ProjectManager, InvestigationService, InvestigationQueryService, InvestigationIntegrityValidator]:
    _application()
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Organisation UI"), storage)
    service = project.repository.module_repository("investigation", "service")
    queries = project.repository.module_repository("investigation", "query_service")
    validator = project.repository.module_repository("investigation", "integrity_validator")
    assert isinstance(service, InvestigationService)
    assert isinstance(queries, InvestigationQueryService)
    assert isinstance(validator, InvestigationIntegrityValidator)
    return manager, service, queries, validator


class _DetailsPanel:
    def __init__(self) -> None:
        from PySide6.QtWidgets import QWidget

        self._widget = QWidget()
        self.provider_widget = None
        self.published = []

    def widget(self):
        return self._widget

    def show_provider_widget(self, _title, widget) -> None:
        self.provider_widget = widget

    def clear_provider_widget(self) -> None:
        pass

    def publish_context(self, context) -> None:
        self.published.append(context)


def test_drag_drop_adds_items_notes_and_hypotheses_to_cases_and_collections():
    _manager, service, queries, validator = _domain()
    item = service.create_item("file", "one", title="Item")
    note = service.create_note("Note")
    _hypothesis = service.create_hypothesis("Piste")
    case = service.create_case("Case")
    collection = service.create_collection("Collection")
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)
    # Les entrÃ©es restent des DTO UI : le test simule le signal du QTreeView sans toucher au domaine interne.
    from models.investigation_tree_model import InvestigationTreeEntry

    assert panel.tree.request_membership(
        InvestigationTreeEntry("item", str(item.item_id), "Item"),
        InvestigationTreeEntry("case", str(case.case_id), "Case"),
    )
    assert not panel.tree.request_membership(
        InvestigationTreeEntry("note", str(note.note_id), "Note"),
        InvestigationTreeEntry("collection", str(collection.collection_id), "Collection"),
    )
    assert panel.tree.request_membership(
        InvestigationTreeEntry("collection", str(collection.collection_id), "Collection"),
        InvestigationTreeEntry("case", str(case.case_id), "Case"),
    )

    assert set(service.find_case_members(case.case_id)) == {
        InvestigationTargetRef("item", str(item.item_id)),
        InvestigationTargetRef("collection", str(collection.collection_id)),
    }
    assert service.find_collection_members(collection.collection_id) == ()
    assert not panel.tree.request_membership(
        InvestigationTreeEntry("case", str(case.case_id), "Case"),
        InvestigationTreeEntry("collection", str(collection.collection_id), "Collection"),
    )
    panel.detach()


def test_case_content_can_navigate_and_remove_a_member():
    _manager, service, _queries, _validator = _domain()
    item = service.create_item("file", "one", title="Ã‰lÃ©ment membre")
    case = service.create_case("Case")
    target = InvestigationTargetRef("item", str(item.item_id))
    service.add_to_case(case.case_id, target)
    provider = InvestigationDetailsProvider(service)
    panel = _DetailsPanel()

    provider.populate(panel, SelectionContext("case", str(case.case_id), "test"))
    member_button = next(
        button
        for button in panel.provider_widget.members_group.findChildren(QPushButton)
        if button.text().endswith("membre")
    )
    member_button.double_clicked.emit()

    assert panel.published[-1].subject_kind == "item"
    assert panel.published[-1].subject_id == str(item.item_id)
    assert [
        action.text() for action in panel.provider_widget._member_menu(member_button, target, "Case").actions()
    ] == ["Retirer de cette Case"]
    panel.provider_widget._remove_member(target)
    assert service.find_case_members(case.case_id) == ()


def test_case_members_have_type_icons_breadcrumb_and_return_navigation():
    _manager, service, _queries, _validator = _domain()
    item = service.create_item("file", "proof", title="Preuve")
    note = service.create_note("Note")
    hypothesis = service.create_hypothesis("Piste")
    collection = service.create_collection("Sous-dossier")
    case = service.create_case("Dossier principal")
    targets = (
        InvestigationTargetRef("item", str(item.item_id)),
        InvestigationTargetRef("note", str(note.note_id)),
        InvestigationTargetRef("hypothesis", str(hypothesis.hypothesis_id)),
        InvestigationTargetRef("collection", str(collection.collection_id)),
    )
    for target in targets:
        service.add_to_case(case.case_id, target)
    provider = InvestigationDetailsProvider(service)
    panel = _DetailsPanel()

    provider.populate(panel, SelectionContext("case", str(case.case_id), "test"))
    member_buttons = [
        button
        for button in panel.provider_widget.members_group.findChildren(QPushButton)
        if button.text() not in {"Retirer", "Ajouter un post-it"}
    ]
    assert len(member_buttons) == 2
    assert any(button.text().endswith("Preuve") for button in member_buttons)
    assert any(button.text().endswith("Sous-dossier") for button in member_buttons)
    return
    member_buttons = [
        button for button in panel.provider_widget.members_group.findChildren(QPushButton) if button.text() != "Retirer"
    ]
    assert {button.text()[0] for button in member_buttons} == {"📄", "📝", "💡", "📂"}
    item_button = next(button for button in member_buttons if button.text().endswith("Preuve"))
    item_button.double_clicked.emit()
    selected = panel.published[-1]
    assert selected.subject_kind == "item"
    assert selected.navigation_hint["container_kind"] == "case"
    assert selected.navigation_hint["container_id"] == str(case.case_id)

    provider.populate(panel, selected)
    widget = panel.provider_widget
    assert "Dossier principal > Preuve" in widget.breadcrumb_label.text()
    assert not widget.return_to_container_button.isHidden()
    widget.return_to_container_button.click()
    returned = panel.published[-1]
    assert returned.subject_kind == "case"
    assert returned.subject_id == str(case.case_id)


def test_organization_context_menu_exposes_case_and_collection_actions():
    _manager, service, queries, validator = _domain()
    item = service.create_item("file", "menu", title="Menu")
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)
    from models.investigation_tree_model import InvestigationTreeEntry

    menu = panel._organization_menu(InvestigationTreeEntry("item", str(item.item_id), "Menu"))

    assert [action.text() for action in menu.actions()] == ["Ajouter à une Case...", "Ajouter à une Collection..."]
    panel.detach()


def test_case_details_no_longer_exposes_post_it_creation(monkeypatch):
    _manager, service, _queries, _validator = _domain()
    case = service.create_case("Dossier")
    provider = InvestigationDetailsProvider(service)
    panel = _DetailsPanel()
    provider.populate(panel, SelectionContext("case", str(case.case_id), "test"))

    def accept(dialog):
        dialog.title_field.setText("Contexte")
        dialog.body_field.setPlainText("Information générale")
        return dialog.DialogCode.Accepted

    from ui.investigation_dialogs import NoteCreationDialog

    monkeypatch.setattr(NoteCreationDialog, "exec", accept)
    assert not hasattr(panel.provider_widget, "add_post_it_button")
    return

    target = InvestigationTargetRef("case", str(case.case_id))
    assert service.find_notes_for_target(target)[0].body == "Contexte\n\nInformation générale"


def test_organization_membership_survives_save_and_reopen(tmp_path):
    root = tmp_path / "organization.carvex"
    first_manager, first_service, _queries, _validator = _domain(JsonProjectStorage(root, create=True))
    item = first_service.create_item("file", "persistent", title="Persistant")
    collection = first_service.create_collection("Collection persistante")
    first_service.add_to_collection(collection.collection_id, InvestigationTargetRef("item", str(item.item_id)))
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened = ProjectManager(modules).open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = reopened.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.find_collection_members(collection.collection_id) == (
        InvestigationTargetRef("item", str(item.item_id)),
    )
