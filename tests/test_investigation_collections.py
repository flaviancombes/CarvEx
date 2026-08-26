"""Tests de la phase 7 : Collections Investigation."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from investigation.collection import CollectionMembership, InvestigationCollection
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
    project = manager.create_project(ProjectMetadata("Collections Investigation"), storage)
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


def test_collection_create_update_and_delete():
    _manager, service = _service()
    collection = service.create_collection("Photos importantes", description="Première revue", created_by="alice")

    assert service.get_collection(collection.collection_id) == collection
    updated = replace(
        collection,
        title="Photos à inclure",
        updated_at=collection.updated_at + timedelta(seconds=1),
    )
    assert service.update_collection(updated) == updated

    service.delete_collection(collection.collection_id)

    assert service.get_collection(collection.collection_id) is None
    assert service.list_collections() == ()


def test_collection_memberships_are_unique_and_removed_with_collection():
    _manager, service = _service()
    collection = service.create_collection("Documents suspects")
    target = _target("file", "file-1")
    membership = service.add_to_collection(collection.collection_id, target, added_by="alice")

    duplicate_collection = InvestigationCollection(
        collection_id=collection.collection_id,
        title="Identifiant dupliqué",
    )
    _raises(ValueError, lambda: service.manager.create_collection(duplicate_collection))
    _raises(ValueError, lambda: service.add_to_collection(collection.collection_id, target))
    duplicate_id = CollectionMembership(
        membership_id=membership.membership_id,
        collection_id=collection.collection_id,
        target_ref=_target("file", "file-2"),
    )
    _raises(ValueError, lambda: service.manager.add_to_collection(duplicate_id))

    service.delete_collection(collection.collection_id)

    assert service.find_collections_for_target(target) == ()


def test_collection_memberships_can_be_removed_and_indexes_rebuilt():
    _manager, service = _service()
    first_collection = service.create_collection("USB")
    second_collection = service.create_collection("Malware")
    target = _target("timeline_event", "event-1")
    service.add_to_collection(first_collection.collection_id, target)
    service.add_to_collection(second_collection.collection_id, target)

    service.manager.rebuild_indexes()

    assert set(service.find_collection_members(first_collection.collection_id)) == {target}
    assert {collection.collection_id for collection in service.find_collections_for_target(target)} == {
        first_collection.collection_id,
        second_collection.collection_id,
    }

    service.remove_from_collection(first_collection.collection_id, target)
    assert service.find_collection_members(first_collection.collection_id) == ()
    assert {collection.collection_id for collection in service.find_collections_for_target(target)} == {
        second_collection.collection_id
    }


def test_collections_round_trip_through_json_and_project_reopen(tmp_path):
    root = tmp_path / "collections.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    collection = first_service.create_collection("Rapport", description="À inclure", created_by="alice")
    target = _target("investigation_item", "item-1")
    first_service.add_to_collection(collection.collection_id, target)
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.get_collection(collection.collection_id) == collection
    assert set(service.find_collection_members(collection.collection_id)) == {target}


def test_existing_investigation_project_is_migrated_to_collections_schema():
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(
        ProjectManifest(
            capabilities=frozenset({"investigation"}),
            enabled_modules=frozenset({"investigation"}),
            module_schemas={"investigation": 1},
        ),
        ProjectMetadata("Projet Investigation antérieur aux Collections"),
    )
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())

    project = ProjectManager(modules).open_repository(repository)
    service = project.repository.module_repository("investigation", "service")

    assert project.manifest.module_schemas == {"investigation": 4}
    assert isinstance(service, InvestigationService)
    assert service.list_collections() == ()
