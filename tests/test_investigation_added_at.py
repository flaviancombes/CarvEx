"""Régressions de la date d'ajout des preuves dans l'arbre Investigation."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from investigation.module import InvestigationProjectModule
from investigation.queries import InvestigationQueryService
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from models.investigation_tree_model import InvestigationSection, InvestigationTreeEntry, InvestigationTreeModel
from project.codecs import ProjectCodecRegistry
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.storage import InMemoryProjectStorage
from ui.investigation_view import InvestigationPanel


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _service(storage=None) -> tuple[ProjectManager, InvestigationService]:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Ajout Investigation"), storage)
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return manager, service


def test_item_creation_and_batch_keep_their_utc_added_timestamp():
    _manager, service = _service()

    item = service.create_item("file", "file-1")
    batch = service.create_items_batch(
        (InvestigationTargetRef("file", "file-2"), InvestigationTargetRef("file", "file-3"))
    )

    assert item.created_at is not None and item.created_at.tzinfo is not None
    assert all(created.created_at is not None and created.created_at.tzinfo is not None for created in batch.applied)


def test_duplicate_batch_preserves_the_original_added_timestamp():
    _manager, service = _service()
    target = InvestigationTargetRef("file", "file-1")
    first = service.create_items_batch((target,)).applied[0]
    second = service.create_items_batch((target,))

    assert second.applied == ()
    assert second.skipped == (first,)
    assert service.get_item(first.item_id).created_at == first.created_at  # type: ignore[union-attr]


def test_added_timestamp_survives_persistence_without_change():
    storage = InMemoryProjectStorage()
    manager, service = _service(storage)
    item = service.create_item("file", "file-1")
    repository = manager.active_project.repository
    manager.save_project()
    manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened = ProjectManager(modules).open_repository(repository)

    reopened_service = reopened.repository.module_repository("investigation", "service")
    assert isinstance(reopened_service, InvestigationService)
    assert reopened_service.get_item(item.item_id).created_at == item.created_at  # type: ignore[union-attr]


def test_legacy_item_without_created_at_remains_unknown_instead_of_becoming_now():
    registry = ProjectCodecRegistry()
    InvestigationProjectModule().register_codecs(registry)
    codec = registry.resolve("dataclass:investigation.item.InvestigationItem")
    _manager, service = _service()
    item = service.create_item("file", "file-1")
    payload = dict(codec.encode(item))
    del payload["created_at"]

    decoded = codec.decode(payload)

    assert decoded.created_at is None


def test_tree_displays_local_added_timestamp_and_a_stable_missing_value():
    _application()
    model = InvestigationTreeModel()
    timestamp = datetime(2026, 9, 3, 16, 24, 17, tzinfo=UTC)
    model.set_entries(
        InvestigationSection.ITEMS,
        (
            InvestigationTreeEntry("item", "one", "Preuve", added_at=timestamp),
            InvestigationTreeEntry("item", "two", "Ancienne preuve", added_at=None),
        ),
    )
    parent = model.index(0, 0, QModelIndex())

    assert model.columnCount() == 2
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Ajouté le"
    assert model.data(model.index(0, 1, parent)) == timestamp.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    assert model.data(model.index(1, 1, parent)) == "—"


def test_item_creation_refreshes_the_loaded_section_without_model_reset():
    _application()
    manager, service = _service()
    queries = manager.active_project.repository.module_repository("investigation", "query_service")
    validator = manager.active_project.repository.module_repository("investigation", "integrity_validator")
    assert isinstance(queries, InvestigationQueryService)
    panel = InvestigationPanel()
    panel.attach(service, queries, validator)
    panel._load_section(InvestigationSection.ITEMS)
    resets: list[None] = []
    panel.model.modelReset.connect(lambda: resets.append(None))

    service.create_item("file", "file-1", title="Preuve")

    section = panel.model.index(0, 0)
    assert panel.model.data(panel.model.index(0, 1, section)) != "—"
    assert resets == []
    panel.detach()
