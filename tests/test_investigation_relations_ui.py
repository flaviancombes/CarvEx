"""Relations Investigation exposées par les composants Qt."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

import ui.investigation_details_provider as investigation_details_provider
import ui.investigation_view as investigation_view
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
from selection.manager import SelectionManager
from ui.investigation_details_provider import InvestigationDetailsProvider
from ui.investigation_view import InvestigationPanel


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _domain() -> tuple[InvestigationService, InvestigationQueryService, InvestigationIntegrityValidator]:
    _application()
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Relations UI"))
    service = project.repository.module_repository("investigation", "service")
    queries = project.repository.module_repository("investigation", "query_service")
    validator = project.repository.module_repository("investigation", "integrity_validator")
    assert isinstance(service, InvestigationService)
    assert isinstance(queries, InvestigationQueryService)
    assert isinstance(validator, InvestigationIntegrityValidator)
    return service, queries, validator


class _Panel:
    def __init__(self) -> None:
        from PySide6.QtWidgets import QWidget

        self._content = QWidget()
        self.widget_value = None
        self.published = []

    def widget(self):
        return self._content

    def show_provider_widget(self, _title, widget) -> None:
        self.widget_value = widget

    def clear_provider_widget(self) -> None:
        pass

    def publish_context(self, context) -> None:
        self.published.append(context)


def test_service_relations_cover_item_hypothesis_and_note_targets():
    service, _queries, _validator = _domain()
    first = service.create_item("file", "one", title="Premier")
    second = service.create_item("file", "two", title="Second")
    hypothesis = service.create_hypothesis("Piste")
    note = service.create_note("Observation")

    item_relation = service.create_relation(
        InvestigationTargetRef("item", str(first.item_id)),
        InvestigationTargetRef("item", str(second.item_id)),
        InvestigationRelationType.RELATED_TO,
    )
    service.create_relation(
        InvestigationTargetRef("item", str(first.item_id)),
        InvestigationTargetRef("hypothesis", str(hypothesis.hypothesis_id)),
        InvestigationRelationType.CONFIRMS,
    )
    service.create_relation(
        InvestigationTargetRef("note", str(note.note_id)),
        InvestigationTargetRef("item", str(first.item_id)),
        InvestigationRelationType.REFERENCES,
    )

    relations = service.find_relations_for_target(InvestigationTargetRef("item", str(first.item_id)))
    assert {relation.relation_id for relation in relations} == {
        item_relation.relation_id,
        *[
            relation.relation_id
            for relation in service.list_relations()
            if relation.relation_id != item_relation.relation_id
        ],
    }


def test_relation_button_creates_a_relation_via_the_service(monkeypatch):
    service, queries, validator = _domain()
    first = service.create_item("file", "one", title="Premier")
    second = service.create_item("file", "two", title="Second")
    panel = InvestigationPanel()
    selections = SelectionManager()
    panel.attach(service, queries, validator, selections)
    # The selected source is deliberately not the first combo-box entry.
    selections.publish(SelectionContext("item", str(second.item_id), "test"))

    def accept(dialog):
        dialog.destination_field.setCurrentIndex(0)
        dialog.relation_type_field.setCurrentIndex(0)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_view.RelationCreationDialog, "exec", accept)
    panel.create_relation_button.click()

    relation = service.list_relations()[0]
    assert relation.source_target == InvestigationTargetRef("item", str(second.item_id))
    assert relation.destination_target == InvestigationTargetRef("item", str(first.item_id))
    panel.detach()


def test_relation_rows_navigate_to_the_linked_object_and_can_be_removed():
    service, _queries, _validator = _domain()
    first = service.create_item("file", "one", title="Premier")
    second = service.create_item("file", "two", title="Second")
    relation = service.create_relation(
        InvestigationTargetRef("item", str(first.item_id)),
        InvestigationTargetRef("item", str(second.item_id)),
        InvestigationRelationType.RELATED_TO,
    )
    provider = InvestigationDetailsProvider(service)
    panel = _Panel()
    from selection.context import SelectionContext

    provider.populate(panel, SelectionContext("item", str(first.item_id), "test"))
    buttons = panel.widget_value.relations_group.findChildren(QPushButton)
    navigate = next(button for button in buttons if button.text().endswith("Second"))
    remove = next(button for button in buttons if button.text() == "Supprimer")

    navigate.click()

    assert panel.published[-1].subject_kind == "item"
    assert panel.published[-1].subject_id == str(second.item_id)
    remove.click()
    assert service.get_relation(relation.relation_id) is None


def test_details_panel_creates_relation_from_the_current_object(monkeypatch):
    service, _queries, _validator = _domain()
    first = service.create_item("file", "one", title="Premier")
    second = service.create_item("file", "two", title="Second")
    provider = InvestigationDetailsProvider(service)
    panel = _Panel()
    from selection.context import SelectionContext

    # The provider must use the displayed object, not combo-box row zero.
    provider.populate(panel, SelectionContext("item", str(second.item_id), "test"))

    def accept(dialog):
        dialog.destination_field.setCurrentIndex(0)
        dialog.relation_type_field.setCurrentIndex(1)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(investigation_details_provider.RelationCreationDialog, "exec", accept)
    panel.widget_value.create_relation_button.click()

    relation = service.list_relations()[0]
    assert relation.source_target == InvestigationTargetRef("item", str(second.item_id))
    assert relation.destination_target == InvestigationTargetRef("item", str(first.item_id))
    assert any("soutient" in label.text() for label in panel.widget_value.relations_group.findChildren(QLabel))
