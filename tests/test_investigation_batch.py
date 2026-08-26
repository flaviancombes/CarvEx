"""Contrat de scalabilité des commandes Investigation de masse."""

from __future__ import annotations

from investigation.events import EventType, InvestigationEvent
from investigation.module import InvestigationProjectModule
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage


def _service(storage=None) -> tuple[ProjectManager, InvestigationService]:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Batch Investigation"), storage)
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return manager, service


def test_create_items_batch_deduplicates_and_publishes_one_completion_event():
    _manager, service = _service()
    bus = service.event_bus
    assert bus is not None
    received: list[InvestigationEvent] = []
    bus.subscribe(received.append)

    result = service.create_items_batch(
        (
            InvestigationTargetRef("file", "file-1"),
            InvestigationTargetRef("file", "file-2"),
            InvestigationTargetRef("file", "file-1"),
        )
    )

    assert result.requested_count == 3
    assert result.applied_count == 2
    assert len(service.list_items()) == 2
    assert [event.event_type for event in received] == [EventType.BATCH_COMPLETED]


def test_create_items_batch_scales_linearly_without_per_item_events():
    _manager, service = _service()
    bus = service.event_bus
    assert bus is not None
    received: list[InvestigationEvent] = []
    bus.subscribe(received.append)
    targets = tuple(InvestigationTargetRef("file", f"file-{index}") for index in range(10_000))

    result = service.create_items_batch(targets)

    assert result.applied_count == len(targets)
    assert len(service.list_items()) == len(targets)
    assert [event.event_type for event in received] == [EventType.BATCH_COMPLETED]


def test_add_files_to_collection_batch_creates_or_reuses_items_and_memberships():
    _manager, service = _service()
    collection = service.create_collection("À analyser")
    existing = service.create_item("file", "file-1")
    bus = service.event_bus
    assert bus is not None
    received: list[InvestigationEvent] = []
    bus.subscribe(received.append)

    result = service.add_files_to_collection_batch(collection.collection_id, ("file-1", "file-2", "file-2"))

    assert result.applied_count == 2
    assert service.find_item_by_subject("file", "file-1") == existing
    assert service.find_item_by_subject("file", "file-2") is not None
    assert {target.target_id for target in service.find_collection_members(collection.collection_id)} == {
        str(existing.item_id),
        str(service.find_item_by_subject("file", "file-2").item_id),
    }
    assert [event.event_type for event in received] == [EventType.BATCH_COMPLETED]


def test_batch_items_and_collection_memberships_round_trip_through_json(tmp_path):
    root = tmp_path / "batch.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    collection = first_service.create_collection("Rapport")
    first_service.add_files_to_collection_batch(collection.collection_id, ("file-1", "file-2", "file-3"))
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened = ProjectManager(modules).open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = reopened.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)

    assert len(service.list_items()) == 3
    assert len(service.find_collection_members(collection.collection_id)) == 3
