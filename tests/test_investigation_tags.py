from dataclasses import fields, replace
from datetime import timedelta

from investigation.module import InvestigationProjectModule
from investigation.service import InvestigationService
from investigation.tag import TagAssignment, normalize_tag_name
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
    project = manager.create_project(ProjectMetadata("Tags Investigation"), storage)
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return manager, service


def _target(kind: str, identifier: str) -> InvestigationTargetRef:
    return InvestigationTargetRef(kind, identifier)


def _raises(expected_exception, callback) -> None:
    try:
        callback()
    except expected_exception:
        return
    raise AssertionError(f"{expected_exception.__name__} attendu")


def test_tag_create_update_and_delete():
    _manager, service = _service()
    tag = service.create_tag("Important", color="#ff0000", description="Prioritaire")

    assert service.get_tag(tag.tag_id) == tag
    assert tag.normalized_name == "important"

    updated = replace(
        tag,
        display_name="Urgent",
        normalized_name=normalize_tag_name("Urgent"),
        updated_at=tag.updated_at + timedelta(seconds=1),
    )
    assert service.update_tag(updated) == updated

    service.delete_tag(tag.tag_id)

    assert service.get_tag(tag.tag_id) is None
    assert service.list_tags() == ()


def test_normalized_tag_names_and_assignments_are_unique():
    _manager, service = _service()
    tag = service.create_tag("Important")
    target = _target("file", "file-1")

    _raises(ValueError, lambda: service.create_tag("  important  "))
    assignment = service.assign_tag(tag.tag_id, target, assigned_by="alice")
    _raises(ValueError, lambda: service.assign_tag(tag.tag_id, target))

    duplicate_assignment = TagAssignment(
        assignment_id=assignment.assignment_id,
        tag_id=tag.tag_id,
        target_ref=_target("file", "file-2"),
    )
    _raises(ValueError, lambda: service.manager.assign_tag(duplicate_assignment))


def test_tag_assignments_indexes_and_usage_count_are_reconstructible():
    project_manager, service = _service()
    tag = service.create_tag("Important")
    first = _target("file", "file-1")
    second = _target("timeline_event", "event-1")
    service.assign_tag(tag.tag_id, first)
    service.assign_tag(tag.tag_id, second)

    assert service.tag_usage_count(tag.tag_id) == 2
    service.manager.rebuild_indexes()
    assert service.tag_usage_count(tag.tag_id) == 2
    assert {item.tag_id for item in service.find_tags_for_target(first)} == {tag.tag_id}
    assert set(service.find_targets_for_tag(tag.tag_id)) == {first, second}

    service.unassign_tag(tag.tag_id, first)
    assert service.tag_usage_count(tag.tag_id) == 1

    snapshot = project_manager.active_project.repository.snapshot()
    persisted_tag = next(iter(snapshot["module:investigation:tags"].values()))
    assert "usage_count" not in {field.name for field in fields(persisted_tag)}


def test_tag_delete_removes_its_assignments():
    _manager, service = _service()
    tag = service.create_tag("Temporaire")
    target = _target("file", "file-1")
    service.assign_tag(tag.tag_id, target)

    service.delete_tag(tag.tag_id)

    assert service.find_tags_for_target(target) == ()


def test_tags_round_trip_through_json_and_project_reopen(tmp_path):
    root = tmp_path / "tags.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    tag = first_service.create_tag("Important", color="#ff0000")
    target = _target("investigation_item", "item-1")
    first_service.assign_tag(tag.tag_id, target, assigned_by="alice")
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.get_tag(tag.tag_id) == tag
    assert {result.tag_id for result in service.find_tags_for_target(target)} == {tag.tag_id}
    assert service.tag_usage_count(tag.tag_id) == 1
