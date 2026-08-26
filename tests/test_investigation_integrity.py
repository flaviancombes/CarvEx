"""Tests de la phase de validation d'intégrité Investigation."""

from __future__ import annotations

from investigation.hypothesis import HypothesisRole
from investigation.integrity import InvestigationIntegrityValidator
from investigation.module import InvestigationProjectModule
from investigation.relation import InvestigationRelation, InvestigationRelationType
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry


def _service() -> InvestigationService:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Intégrité Investigation"))
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return service


def test_valid_domain_returns_an_empty_report():
    service = _service()
    target = InvestigationTargetRef("file", "file-1")
    service.create_item("file", "file-1")
    service.create_note("Observation", target_ref=target)
    tag = service.create_tag("Important")
    service.assign_tag(tag.tag_id, target)
    collection = service.create_collection("À analyser")
    service.add_to_collection(collection.collection_id, target)
    case = service.create_case("Affaire A")
    service.add_to_case(case.case_id, target)
    hypothesis = service.create_hypothesis("Piste A")
    service.add_to_hypothesis(hypothesis.hypothesis_id, target, HypothesisRole.SUPPORTS)

    report = InvestigationIntegrityValidator(service, lambda _target: True).validate()

    assert report.issues == ()
    assert report.is_valid
    assert not report.has_warnings


def test_orphan_reference_after_partial_deletion_is_reported_without_mutation():
    service = _service()
    existing = {"file-1"}
    target = InvestigationTargetRef("file", "file-1")
    case = service.create_case("Affaire A")
    service.add_to_case(case.case_id, target)
    existing.remove("file-1")

    report = InvestigationIntegrityValidator(service, lambda ref: ref.target_id in existing).validate()

    assert any(issue.code == "orphan_case_membership" and issue.target_ref == target for issue in report.issues)
    assert service.find_case_members(case.case_id) == (target,)


def test_incoherent_journal_target_is_reported():
    service = _service()
    target = InvestigationTargetRef("file", "deleted-file")
    service.create_note("Trace d'une cible supprimée", target_ref=target)

    report = InvestigationIntegrityValidator(service, lambda _ref: False).validate()

    assert any(issue.code == "orphan_note_target" for issue in report.issues)
    assert any(issue.code == "orphan_journal_target" for issue in report.issues)


class _DuplicateRelationDomain:
    """Façade publique contrôlée simulant une corruption lisible du domaine."""

    def __init__(self, relations: tuple[InvestigationRelation, ...]) -> None:
        self._relations = relations

    def list_items(self):
        return ()

    def list_cases(self):
        return ()

    def list_collections(self):
        return ()

    def list_hypotheses(self):
        return ()

    def list_notes(self):
        return ()

    def list_tags(self):
        return ()

    def list_entries(self):
        return ()

    def list_relations(self):
        return self._relations


def test_logical_relation_duplicates_are_detected_from_public_read_model():
    source = InvestigationTargetRef("file", "file-1")
    destination = InvestigationTargetRef("file", "file-2")
    first = InvestigationRelation("relation-1", source, destination, InvestigationRelationType.DUPLICATES)
    second = InvestigationRelation("relation-2", destination, source, InvestigationRelationType.DUPLICATES)

    report = InvestigationIntegrityValidator(_DuplicateRelationDomain((first, second)), lambda _ref: True).validate()

    assert any(issue.code == "duplicate_logical_relation" for issue in report.issues)
