"""Régressions de l'organisation en masse depuis l'arbre Investigation."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from investigation.events import EventType
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


def _panel() -> tuple[InvestigationPanel, InvestigationService]:
    _application()
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Organisation groupée"))
    service = project.repository.module_repository("investigation", "service")
    queries = project.repository.module_repository("investigation", "query_service")
    validator = project.repository.module_repository("investigation", "integrity_validator")
    assert isinstance(service, InvestigationService)
    assert isinstance(queries, InvestigationQueryService)
    assert isinstance(validator, InvestigationIntegrityValidator)
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)
    return panel, service


def _items(service: InvestigationService, count: int):
    return tuple(service.create_item("file", f"file-{number}", title=f"Preuve {number}") for number in range(count))


def _select_items(panel: InvestigationPanel, count: int) -> tuple[str, ...]:
    panel._load_section(InvestigationSection.ITEMS)
    section = panel.model.index(0, 0)
    selection = panel.tree.selectionModel()
    for row in range(count):
        selection.select(
            panel.model.index(row, 0, section),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    return tuple(entry.subject_id for entry in panel.tree.selected_item_entries())


def test_tree_uses_native_extended_selection_and_deduplicates_rows():
    panel, service = _panel()
    _items(service, 5)

    selected = _select_items(panel, 5)

    assert panel.tree.selectionMode() == panel.tree.SelectionMode.ExtendedSelection
    assert len(selected) == 5
    assert len(set(selected)) == 5
    panel.detach()


def test_mixed_selection_ignores_sections_and_keeps_only_items():
    panel, service = _panel()
    items = _items(service, 2)
    selected = _select_items(panel, 2)
    panel.tree.selectionModel().select(panel.model.index(1, 0), QItemSelectionModel.SelectionFlag.Select)

    assert selected == tuple(str(item.item_id) for item in items)
    assert tuple(entry.subject_id for entry in panel.tree.selected_item_entries()) == selected
    panel.detach()


@pytest.mark.parametrize("count", (1, 5, 50, 500))
def test_bulk_case_memberships_are_idempotent_and_publish_one_batch_event(count: int):
    panel, service = _panel()
    items = _items(service, count)
    case = service.create_case("Identification")
    received = []
    assert service.event_bus is not None
    service.event_bus.subscribe(received.append)

    result = service.add_items_to_case_batch(case.case_id, tuple(str(item.item_id) for item in items))
    repeated = service.add_items_to_case_batch(case.case_id, tuple(str(item.item_id) for item in items))

    assert result.applied_count == count
    assert repeated.applied_count == 0
    assert repeated.skipped_count == count
    assert set(service.find_case_members(case.case_id)) == {
        InvestigationTargetRef("item", str(item.item_id)) for item in items
    }
    assert [event.event_type for event in received] == [EventType.BATCH_COMPLETED, EventType.BATCH_COMPLETED]
    assert all(service.get_item(item.item_id).created_at == item.created_at for item in items)  # type: ignore[union-attr]
    panel.detach()


def test_bulk_collection_from_tree_keeps_selection_and_never_resets_the_model():
    panel, service = _panel()
    items = _items(service, 5)
    collection = service.create_collection("Documents")
    selected = _select_items(panel, 5)
    resets: list[None] = []
    panel.model.modelReset.connect(lambda: resets.append(None))

    assert panel._controller is not None
    panel._controller.add_items_to_container(
        panel.tree.selected_item_entries(), "collection", str(collection.collection_id)
    )

    assert set(service.find_collection_members(collection.collection_id)) == {
        InvestigationTargetRef("item", str(item.item_id)) for item in items
    }
    assert tuple(entry.subject_id for entry in panel.tree.selected_item_entries()) == selected
    assert resets == []
    panel.detach()
