from dataclasses import replace
from datetime import timedelta

from investigation.item import InvestigationItem, InvestigationPriority, InvestigationStatus
from investigation.module import InvestigationProjectModule
from investigation.service import InvestigationService
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage, JsonProjectStorage


def _service(storage=None) -> tuple[ProjectManager, InvestigationService]:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Items Investigation"), storage)
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return manager, service


def _raises(expected_exception, callback) -> None:
    try:
        callback()
    except expected_exception:
        return
    raise AssertionError(f"{expected_exception.__name__} attendu")


def test_investigation_item_create_update_and_delete():
    _manager, service = _service()
    item = service.create_item(
        "file",
        "file-1",
        title="Élément initial",
        priority=InvestigationPriority.HIGH,
        status=InvestigationStatus.TO_ANALYZE,
    )

    assert service.get_item(item.item_id) == item
    assert service.find_item_by_subject("file", "file-1") == item

    updated = replace(
        item,
        title="Élément confirmé",
        status=InvestigationStatus.VALIDATED,
        updated_at=item.updated_at + timedelta(seconds=1),
    )
    assert service.update_item(updated) == updated
    assert service.get_item(item.item_id) == updated

    service.delete_item(item.item_id)

    assert service.get_item(item.item_id) is None
    assert service.find_item_by_subject("file", "file-1") is None
    assert service.list_items() == ()


def test_investigation_item_identifiers_and_subject_references_are_unique():
    _project_manager, service = _service()
    first = service.create_item("file", "file-1")

    _raises(ValueError, lambda: service.create_item("file", "file-1"))
    duplicate_id = InvestigationItem(
        item_id=first.item_id,
        subject_kind="timeline_event",
        subject_id="event-1",
    )
    _raises(ValueError, lambda: service.manager.create_item(duplicate_id))

    changed_subject = replace(
        first,
        subject_id="file-2",
        updated_at=first.updated_at + timedelta(seconds=1),
    )
    _raises(ValueError, lambda: service.update_item(changed_subject))


def test_investigation_item_indexes_are_reconstructible():
    _project_manager, service = _service()
    first = service.create_item("file", "file-1")
    second = service.create_item("timeline_event", "event-1")

    service.manager.rebuild_indexes()

    assert service.get_item(first.item_id) == first
    assert service.find_item_by_subject("timeline_event", "event-1") == second
    assert {item.item_id for item in service.list_items()} == {first.item_id, second.item_id}


def test_investigation_items_survive_project_save_and_reopen():
    storage = InMemoryProjectStorage()
    first_manager, first_service = _service(storage)
    created = first_service.create_item("file", "persistent-file", title="Persistant")
    repository = first_manager.active_project.repository
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(repository)
    reopened_service = project.repository.module_repository("investigation", "service")

    assert isinstance(reopened_service, InvestigationService)
    assert reopened_service.get_item(created.item_id) == created
    assert reopened_service.find_item_by_subject("file", "persistent-file") == created


def test_investigation_items_round_trip_through_json_project_storage(tmp_path):
    root = tmp_path / "items.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    created = first_service.create_item(
        "file",
        "json-file",
        priority=InvestigationPriority.CRITICAL,
        status=InvestigationStatus.IN_PROGRESS,
    )
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    reopened_service = project.repository.module_repository("investigation", "service")

    assert isinstance(reopened_service, InvestigationService)
    assert reopened_service.get_item(created.item_id) == created
