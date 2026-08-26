"""Tests de la phase 11 : projections de lecture Investigation."""

from __future__ import annotations

from investigation.hypothesis import HypothesisRole
from investigation.module import InvestigationProjectModule
from investigation.queries import InvestigationQueryService
from investigation.relation import InvestigationRelationType
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry


def _services() -> tuple[InvestigationService, InvestigationQueryService]:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Requêtes Investigation"))
    service = project.repository.module_repository("investigation", "service")
    queries = project.repository.module_repository("investigation", "query_service")
    assert isinstance(service, InvestigationService)
    assert isinstance(queries, InvestigationQueryService)
    return service, queries


def test_target_context_reuses_all_existing_domain_indexes():
    service, queries = _services()
    target = InvestigationTargetRef("file", "file-1")
    related = InvestigationTargetRef("timeline_event", "event-1")
    item = service.create_item("file", "file-1")
    note = service.create_note("Élément important", target_ref=target)
    tag = service.create_tag("Important")
    service.assign_tag(tag.tag_id, target)
    relation = service.create_relation(target, related, InvestigationRelationType.RELATED_TO)
    collection = service.create_collection("À analyser")
    service.add_to_collection(collection.collection_id, target)
    case = service.create_case("Affaire A")
    service.add_to_case(case.case_id, target)
    hypothesis = service.create_hypothesis("Piste A")
    service.add_to_hypothesis(hypothesis.hypothesis_id, target, HypothesisRole.SUPPORTS)

    context = queries.get_target_context(target)

    assert context.item == item
    assert context.notes == (note,)
    assert context.tags == (tag,)
    assert context.relations == (relation,)
    assert context.collections == (collection,)
    assert context.cases == (case,)
    assert context.hypotheses == (hypothesis,)
    assert context.journal_entries == service.find_entries_for_target(target)


def test_case_context_contains_members_and_only_direct_case_associations():
    service, queries = _services()
    member = InvestigationTargetRef("file", "file-1")
    case = service.create_case("Affaire A")
    case_ref = InvestigationTargetRef("case", str(case.case_id))
    service.add_to_case(case.case_id, member)
    note = service.create_note("Note de l'affaire", target_ref=case_ref)
    tag = service.create_tag("Prioritaire")
    service.assign_tag(tag.tag_id, case_ref)
    collection = service.create_collection("Éléments de l'affaire")
    service.add_to_collection(collection.collection_id, case_ref)
    hypothesis = service.create_hypothesis("Hypothèse de l'affaire")
    service.add_to_hypothesis(hypothesis.hypothesis_id, case_ref, HypothesisRole.OBSERVATION)

    context = queries.get_case_context(case.case_id)

    assert context.case == case
    assert context.members == (member,)
    assert context.notes == (note,)
    assert context.tags == (tag,)
    assert context.collections == (collection,)
    assert context.hypotheses == (hypothesis,)


def test_collection_context_contains_members_notes_and_tags():
    service, queries = _services()
    member = InvestigationTargetRef("file", "file-1")
    collection = service.create_collection("Collection A")
    collection_ref = InvestigationTargetRef("collection", str(collection.collection_id))
    service.add_to_collection(collection.collection_id, member)
    note = service.create_note("Note de collection", target_ref=collection_ref)
    tag = service.create_tag("Collection")
    service.assign_tag(tag.tag_id, collection_ref)

    context = queries.get_collection_context(collection.collection_id)

    assert context.collection == collection
    assert context.members == (member,)
    assert context.notes == (note,)
    assert context.tags == (tag,)


def test_hypothesis_context_preserves_member_roles_and_direct_relations():
    service, queries = _services()
    member = InvestigationTargetRef("file", "file-1")
    related = InvestigationTargetRef("timeline_event", "event-1")
    hypothesis = service.create_hypothesis("Hypothèse A")
    hypothesis_ref = InvestigationTargetRef("hypothesis", str(hypothesis.hypothesis_id))
    membership = service.add_to_hypothesis(hypothesis.hypothesis_id, member, HypothesisRole.CONTRADICTS)
    relation = service.create_relation(hypothesis_ref, related, InvestigationRelationType.REFERENCES)

    context = queries.get_hypothesis_context(hypothesis.hypothesis_id)

    assert context.hypothesis == hypothesis
    assert context.memberships == (membership,)
    assert context.memberships[0].role is HypothesisRole.CONTRADICTS
    assert context.relations == (relation,)
