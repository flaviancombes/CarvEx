"""Tests de la phase 10 : Journal Investigation append-only."""

from __future__ import annotations

from datetime import timedelta

from investigation.events import EventType
from investigation.module import InvestigationProjectModule
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectManifest, ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage, JsonProjectStorage


def _service(storage=None) -> tuple[ProjectManager, InvestigationService]:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Journal Investigation"), storage)
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return manager, service


def test_journal_entry_is_created_automatically_from_a_domain_event():
    _manager, service = _service()
    item = service.create_item("file", "file-1", created_by="alice")

    entries = service.list_entries()

    assert len(entries) == 1
    assert entries[0].event_type is EventType.ITEM_CREATED
    assert entries[0].target_ref == InvestigationTargetRef("file", "file-1")
    assert entries[0].context == {"entity_id": str(item.item_id)}
    assert entries[0].created_by == "alice"


def test_journal_is_chronological_and_can_filter_by_event_type_and_target():
    _manager, service = _service()
    target = InvestigationTargetRef("file", "file-1")
    item = service.create_item("file", "file-1")
    service.update_item(item)
    collection = service.create_collection("A analyser")
    service.add_to_collection(collection.collection_id, target)

    entries = service.list_entries()
    item_entries = service.find_entries_for_target(target)
    created_entries = service.find_entries_by_event_type(EventType.ITEM_CREATED)

    assert entries == tuple(sorted(entries, key=lambda entry: (entry.timestamp, entry.entry_id)))
    assert item_entries == tuple(sorted(item_entries, key=lambda entry: (entry.timestamp, entry.entry_id)))
    assert {entry.event_type for entry in item_entries} == {
        EventType.ITEM_CREATED,
        EventType.ITEM_UPDATED,
        EventType.MEMBERSHIP_ADDED,
    }
    assert len(created_entries) == 1
    assert created_entries[0].context["entity_id"] == str(item.item_id)


def test_journal_indexes_are_reconstructible_and_date_filter_is_inclusive():
    _manager, service = _service()
    service.create_tag("important")
    entries = service.list_entries()
    entry = entries[0]

    service.manager.rebuild_indexes()

    assert service.find_entries_between_dates(
        entry.timestamp - timedelta(seconds=1),
        entry.timestamp + timedelta(seconds=1),
    ) == (entry,)


def test_journal_round_trips_through_json_and_project_reopen(tmp_path):
    root = tmp_path / "journal.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    target = InvestigationTargetRef("file", "file-1")
    first_service.create_note("Observation", target_ref=target, author="alice")
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    entries = service.list_entries()
    assert len(entries) == 1
    assert entries[0].event_type is EventType.NOTE_CREATED
    assert entries[0].target_ref == target
    assert entries[0].created_by == "alice"


def test_investigation_project_v3_is_migrated_to_journal_schema():
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(
        ProjectManifest(
            capabilities=frozenset({"investigation"}),
            enabled_modules=frozenset({"investigation"}),
            module_schemas={"investigation": 3},
        ),
        ProjectMetadata("Projet Investigation v3"),
    )
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())

    project = ProjectManager(modules).open_repository(repository)
    service = project.repository.module_repository("investigation", "service")

    assert project.manifest.module_schemas == {"investigation": 4}
    assert isinstance(service, InvestigationService)
    assert service.list_entries() == ()
