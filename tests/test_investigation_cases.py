from dataclasses import replace
from datetime import timedelta

from investigation.case import CaseMembership, CasePriority, CaseStatus
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
    project = manager.create_project(ProjectMetadata("Cases Investigation"), storage)
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


def test_case_create_update_and_delete():
    _manager, service = _service()
    case = service.create_case("Suppression", status=CaseStatus.IN_PROGRESS, priority=CasePriority.HIGH)

    assert service.get_case(case.case_id) == case
    updated = replace(
        case,
        title="Suppression confirmée",
        updated_at=case.updated_at + timedelta(seconds=1),
    )
    assert service.update_case(updated) == updated

    service.delete_case(case.case_id)

    assert service.get_case(case.case_id) is None
    assert service.list_cases() == ()


def test_case_memberships_are_unique_and_removed_with_case():
    _manager, service = _service()
    case = service.create_case("Exfiltration")
    target = _target("file", "file-1")
    membership = service.add_to_case(case.case_id, target, added_by="alice")

    _raises(ValueError, lambda: service.add_to_case(case.case_id, target))
    duplicate_id = CaseMembership(
        membership_id=membership.membership_id,
        case_id=case.case_id,
        target_ref=_target("file", "file-2"),
    )
    _raises(ValueError, lambda: service.manager.add_to_case(duplicate_id))

    service.delete_case(case.case_id)

    assert service.find_cases_for_target(target) == ()


def test_case_memberships_can_be_removed_and_indexes_rebuilt():
    _manager, service = _service()
    first_case = service.create_case("USB")
    second_case = service.create_case("Malware")
    target = _target("timeline_event", "event-1")
    service.add_to_case(first_case.case_id, target)
    service.add_to_case(second_case.case_id, target)

    service.manager.rebuild_indexes()

    assert set(service.find_case_members(first_case.case_id)) == {target}
    assert {case.case_id for case in service.find_cases_for_target(target)} == {first_case.case_id, second_case.case_id}

    service.remove_from_case(first_case.case_id, target)
    assert service.find_case_members(first_case.case_id) == ()
    assert {case.case_id for case in service.find_cases_for_target(target)} == {second_case.case_id}


def test_cases_round_trip_through_json_and_project_reopen(tmp_path):
    root = tmp_path / "cases.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    case = first_service.create_case("Suppression", description="Analyse", created_by="alice")
    target = _target("investigation_item", "item-1")
    first_service.add_to_case(case.case_id, target)
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.get_case(case.case_id) == case
    assert set(service.find_case_members(case.case_id)) == {target}
