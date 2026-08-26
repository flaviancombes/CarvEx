from dataclasses import replace
from datetime import timedelta

from investigation.module import InvestigationProjectModule
from investigation.relation import InvestigationRelation, InvestigationRelationType
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
    project = manager.create_project(ProjectMetadata("Relations Investigation"), storage)
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


def test_relation_create_update_and_delete():
    _manager, service = _service()
    relation = service.create_relation(
        _target("file", "source"),
        _target("timeline_event", "event-1"),
        InvestigationRelationType.CONFIRMS,
    )

    assert service.get_relation(relation.relation_id) == relation
    assert service.find_relations_for_target(_target("file", "source")) == (relation,)

    updated = replace(
        relation,
        comment="Corrélé à la timeline",
        updated_at=relation.updated_at + timedelta(seconds=1),
    )
    assert service.update_relation(updated) == updated

    service.delete_relation(relation.relation_id)

    assert service.get_relation(relation.relation_id) is None
    assert service.list_relations() == ()


def test_relation_ids_self_references_and_symmetric_duplicates_are_validated():
    _manager, service = _service()
    first_target = _target("file", "b")
    second_target = _target("file", "a")
    relation = service.create_relation(first_target, second_target, InvestigationRelationType.DUPLICATES)

    assert relation.source_target == second_target
    assert relation.destination_target == first_target
    _raises(
        ValueError,
        lambda: service.create_relation(second_target, first_target, InvestigationRelationType.DUPLICATES),
    )
    _raises(
        ValueError,
        lambda: service.create_relation(first_target, first_target, InvestigationRelationType.RELATED_TO),
    )

    duplicate_id = InvestigationRelation(
        relation_id=relation.relation_id,
        source_target=_target("file", "other"),
        destination_target=_target("file", "another"),
        relation_type=InvestigationRelationType.RELATED_TO,
    )
    _raises(ValueError, lambda: service.manager.create_relation(duplicate_id))
    _raises(
        ValueError,
        lambda: InvestigationRelation(
            relation_id="invalid-type",
            source_target=first_target,
            destination_target=second_target,
            relation_type="duplicates",  # type: ignore[arg-type]
        ),
    )


def test_relation_indexes_are_reconstructible():
    _manager, service = _service()
    target = _target("file", "file-1")
    first = service.create_relation(target, _target("timeline_event", "event-1"), InvestigationRelationType.RELATED_TO)
    second = service.create_relation(_target("file", "file-2"), target, InvestigationRelationType.REFERENCES)

    service.manager.rebuild_indexes()

    assert {relation.relation_id for relation in service.find_relations_for_target(target)} == {
        first.relation_id,
        second.relation_id,
    }
    assert {relation.relation_id for relation in service.list_relations()} == {first.relation_id, second.relation_id}


def test_relations_round_trip_through_json_and_project_reopen(tmp_path):
    root = tmp_path / "relations.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    created = first_service.create_relation(
        _target("investigation_item", "item-1"),
        _target("file", "file-1"),
        InvestigationRelationType.DERIVED_FROM,
        comment="Origine identifiée",
    )
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.get_relation(created.relation_id) == created
    assert service.find_relations_for_target(_target("file", "file-1")) == (created,)
