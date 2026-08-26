"""Tests de la phase 8 : Hypothèses Investigation."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from investigation.hypothesis import (
    HypothesisConfidence,
    HypothesisMembership,
    HypothesisRole,
    HypothesisStatus,
    InvestigationHypothesis,
)
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
    project = manager.create_project(ProjectMetadata("Hypothèses Investigation"), storage)
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


def test_hypothesis_create_update_and_delete():
    _manager, service = _service()
    hypothesis = service.create_hypothesis(
        "Le suspect a supprimé les photographies",
        status=HypothesisStatus.IN_PROGRESS,
        confidence=HypothesisConfidence.MEDIUM,
        created_by="alice",
    )

    assert service.get_hypothesis(hypothesis.hypothesis_id) == hypothesis
    updated = replace(
        hypothesis,
        confidence=HypothesisConfidence.HIGH,
        updated_at=hypothesis.updated_at + timedelta(seconds=1),
    )
    assert service.update_hypothesis(updated) == updated

    service.delete_hypothesis(hypothesis.hypothesis_id)

    assert service.get_hypothesis(hypothesis.hypothesis_id) is None
    assert service.list_hypotheses() == ()


def test_hypothesis_memberships_validate_roles_and_are_removed_with_hypothesis():
    _manager, service = _service()
    hypothesis = service.create_hypothesis("Origine des conversations")
    target = _target("file", "file-1")
    membership = service.add_to_hypothesis(hypothesis.hypothesis_id, target, HypothesisRole.SUPPORTS, added_by="alice")

    duplicate_hypothesis = InvestigationHypothesis(
        hypothesis_id=hypothesis.hypothesis_id,
        title="Identifiant dupliqué",
    )
    _raises(ValueError, lambda: service.manager.create_hypothesis(duplicate_hypothesis))
    _raises(ValueError, lambda: service.add_to_hypothesis(hypothesis.hypothesis_id, target, HypothesisRole.CONTRADICTS))
    duplicate_id = HypothesisMembership(
        membership_id=membership.membership_id,
        hypothesis_id=hypothesis.hypothesis_id,
        target_ref=_target("file", "file-2"),
        role=HypothesisRole.OBSERVATION,
    )
    _raises(ValueError, lambda: service.manager.add_to_hypothesis(duplicate_id))
    _raises(
        ValueError,
        lambda: HypothesisMembership(
            membership_id="invalid-role",
            hypothesis_id=hypothesis.hypothesis_id,
            target_ref=_target("file", "file-3"),
            role="supports",  # type: ignore[arg-type]
        ),
    )

    service.delete_hypothesis(hypothesis.hypothesis_id)

    assert service.find_hypotheses_for_target(target) == ()


def test_hypothesis_memberships_can_be_removed_and_indexes_rebuilt():
    _manager, service = _service()
    first_hypothesis = service.create_hypothesis("Suppression")
    second_hypothesis = service.create_hypothesis("Exfiltration")
    target = _target("timeline_event", "event-1")
    first_membership = service.add_to_hypothesis(first_hypothesis.hypothesis_id, target, HypothesisRole.OBSERVATION)
    second_membership = service.add_to_hypothesis(second_hypothesis.hypothesis_id, target, HypothesisRole.REFERENCE)

    service.manager.rebuild_indexes()

    assert set(service.find_hypothesis_members(first_hypothesis.hypothesis_id)) == {target}
    assert {hypothesis.hypothesis_id for hypothesis in service.find_hypotheses_for_target(target)} == {
        first_hypothesis.hypothesis_id,
        second_hypothesis.hypothesis_id,
    }
    assert service.manager._hypothesis_membership_ids_by_role[HypothesisRole.OBSERVATION] == {
        first_membership.membership_id
    }
    assert service.manager._hypothesis_membership_ids_by_role[HypothesisRole.REFERENCE] == {
        second_membership.membership_id
    }

    service.remove_from_hypothesis(first_hypothesis.hypothesis_id, target)
    assert service.find_hypothesis_members(first_hypothesis.hypothesis_id) == ()
    assert {hypothesis.hypothesis_id for hypothesis in service.find_hypotheses_for_target(target)} == {
        second_hypothesis.hypothesis_id
    }


def test_hypotheses_round_trip_through_json_and_project_reopen(tmp_path):
    root = tmp_path / "hypotheses.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    hypothesis = first_service.create_hypothesis(
        "Malware responsable des artefacts",
        confidence=HypothesisConfidence.HIGH,
    )
    target = _target("investigation_item", "item-1")
    first_service.add_to_hypothesis(hypothesis.hypothesis_id, target, HypothesisRole.RESULT)
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.get_hypothesis(hypothesis.hypothesis_id) == hypothesis
    assert set(service.find_hypothesis_members(hypothesis.hypothesis_id)) == {target}


def test_investigation_project_v2_is_migrated_to_hypotheses_schema():
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(
        ProjectManifest(
            capabilities=frozenset({"investigation"}),
            enabled_modules=frozenset({"investigation"}),
            module_schemas={"investigation": 2},
        ),
        ProjectMetadata("Projet Investigation v2"),
    )
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())

    project = ProjectManager(modules).open_repository(repository)
    service = project.repository.module_repository("investigation", "service")

    assert project.manifest.module_schemas == {"investigation": 4}
    assert isinstance(service, InvestigationService)
    assert service.list_hypotheses() == ()
