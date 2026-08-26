"""Persistance, cache et index des métadonnées de projet."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from metadata.base import MetadataCategory, MetadataField, MetadataResult
from metadata.indexing import MetadataIndexingCheckpoint, MetadataIndexingEntry, MetadataIndexingState
from metadata.manager import MetadataManager
from metadata.module import MetadataProjectModule
from metadata.store import MetadataStore
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.storage import InMemoryProjectStorage, JsonProjectStorage
from project.stores import ProjectStore


def _field(identifier: str, value: str) -> MetadataField:
    return MetadataField(identifier, MetadataCategory.EXIF, identifier, value, source="test")


class _Provider:
    provider_id = "test.provider"
    priority = 1

    def __init__(self) -> None:
        self.calls = 0

    def supports(self, _record) -> bool:
        return True

    def extract(self, _record):
        self.calls += 1
        return (_field("exif.model", "Canon"),)


def _manager_with_module(provider):
    metadata_manager = MetadataManager((provider,))
    modules = ProjectModuleRegistry()
    modules.register(MetadataProjectModule(metadata_manager))
    return metadata_manager, ProjectManager(modules)


def test_store_persists_fields_and_index_without_provider_recalculation():
    provider = _Provider()
    manager, projects = _manager_with_module(provider)
    storage = InMemoryProjectStorage()
    project = projects.create_project(ProjectMetadata("Metadata"), storage)
    record = {"file_id": str(uuid4()), "name": "photo.jpg"}

    first = manager.extract(record)
    projects.save_project()
    projects.close_project()

    second_provider = _Provider()
    reopened_manager, reopened_projects = _manager_with_module(second_provider)
    reopened_projects.open_repository(project.repository)
    restored = reopened_manager.extract(record)

    assert restored.fields == first.fields
    assert provider.calls == 1
    assert second_provider.calls == 0
    assert reopened_manager.index.search("canon") == frozenset({record["file_id"]})


def test_json_project_reopens_metadata_store_with_its_typed_fields(tmp_path):
    provider = _Provider()
    manager, projects = _manager_with_module(provider)
    root = tmp_path / "case.carvex"
    projects.create_project(ProjectMetadata("Metadata"), JsonProjectStorage(root, create=True))
    record = {"file_id": str(uuid4()), "name": "photo.jpg"}
    manager.extract(record)
    projects.close_project()

    reopened_manager, reopened_projects = _manager_with_module(_Provider())
    reopened_projects.open_project(root)

    assert reopened_manager.extract(record).fields[0].value == "Canon"
    assert reopened_manager.index.by_category("exif") == frozenset({record["file_id"]})


def test_store_index_handles_large_simulated_metadata_volume():
    storage = InMemoryProjectStorage()
    store = MetadataStore(ProjectStore(storage, "metadata:fields"), ProjectStore(storage, "metadata:index"))
    fields = tuple(_field(f"exif.tag_{index}", f"value {index}") for index in range(300_000))

    store.set("file-1", MetadataResult(fields=fields))

    assert store.index.search("value 299999") == frozenset({"file-1"})


def test_store_replaces_one_file_without_retaining_stale_index_keys():
    storage = InMemoryProjectStorage()
    store = MetadataStore(ProjectStore(storage, "metadata:fields"), ProjectStore(storage, "metadata:index"))
    store.set("file-1", MetadataResult(fields=(_field("exif.model", "Canon"),)))
    store.set("file-1", MetadataResult(fields=(_field("exif.model", "Nikon"),)))

    assert store.index.search("canon") == frozenset()
    assert store.index.search("nikon") == frozenset({"file-1"})


def _checkpoint() -> MetadataIndexingCheckpoint:
    entry = MetadataIndexingEntry("file-1", MetadataIndexingState.INDEXED, datetime.now(UTC))
    return MetadataIndexingCheckpoint(1, 1, 7, 1, 1, 0, {entry.file_id: entry})


def test_store_returns_no_checkpoint_for_a_legacy_project_without_persisting_one():
    storage = InMemoryProjectStorage()
    index_store = ProjectStore(storage, "metadata:index")
    store = MetadataStore(ProjectStore(storage, "metadata:fields"), index_store)

    assert store.load_checkpoint() is None
    assert store.checkpoint is None
    assert MetadataStore.CHECKPOINT_KEY not in set(index_store.keys())


def test_store_persists_and_restores_typed_checkpoint_in_json(tmp_path):
    manager, projects = _manager_with_module(_Provider())
    root = tmp_path / "checkpoint.carvex"
    projects.create_project(ProjectMetadata("Metadata"), JsonProjectStorage(root, create=True))
    store = projects.active_project.repository.module_repository("metadata", "store")
    checkpoint = _checkpoint()
    store.save_checkpoint(checkpoint)
    projects.close_project()

    reopened_manager, reopened_projects = _manager_with_module(_Provider())
    reopened_projects.open_project(root)
    restored_store = reopened_projects.active_project.repository.module_repository("metadata", "store")
    restored = restored_store.load_checkpoint()

    assert restored == checkpoint
    assert restored.entries["file-1"].state is MetadataIndexingState.INDEXED
    assert restored.indexed_count == 1
    assert restored.failed_count == 0
    assert reopened_manager.index is restored_store.index


def test_legacy_state_adapter_persists_only_the_typed_checkpoint():
    storage = InMemoryProjectStorage()
    index_store = ProjectStore(storage, "metadata:index")
    store = MetadataStore(ProjectStore(storage, "metadata:fields"), index_store)

    store.save_indexing_state(
        {
            "schema_version": 1,
            "index_version": 1,
            "last_checkpoint": 0,
            "total": 1,
            "indexed": 0,
            "failed": 1,
            "states": {
                "file-1": {"state": "failed", "changed_at": datetime.now(UTC).isoformat()},
            },
        }
    )

    assert isinstance(index_store.get(MetadataStore.CHECKPOINT_KEY), MetadataIndexingCheckpoint)
    assert store.load_checkpoint().entries["file-1"].state is MetadataIndexingState.FAILED


def test_module_hydrates_indexing_service_without_writing_a_legacy_project():
    storage = InMemoryProjectStorage()
    manager, projects = _manager_with_module(_Provider())
    project = projects.create_project(ProjectMetadata("Metadata"), storage)
    file_id = str(uuid4())
    record = {"file_id": file_id, "name": "legacy.jpg"}
    manager.extract(record)
    projects.save_project()
    projects.close_project()
    storage.flush()

    reopened_manager, reopened_projects = _manager_with_module(_Provider())
    reopened_projects.open_repository(project.repository)
    service = reopened_projects.active_project.repository.module_repository("metadata", "indexing_service")
    store = reopened_projects.active_project.repository.module_repository("metadata", "store")

    assert service.progress.total == 1
    assert service.state_for(file_id) is MetadataIndexingState.NOT_INDEXED
    assert service.dequeue() is None
    assert store.load_checkpoint() is None
    assert reopened_manager.index is not None


def test_module_hydrates_indexing_service_from_the_persisted_checkpoint(tmp_path):
    manager, projects = _manager_with_module(_Provider())
    root = tmp_path / "hydrated.carvex"
    projects.create_project(ProjectMetadata("Metadata"), JsonProjectStorage(root, create=True))
    store = projects.active_project.repository.module_repository("metadata", "store")
    checkpoint = _checkpoint()
    store.save_checkpoint(checkpoint)
    projects.close_project()

    _reopened_manager, reopened_projects = _manager_with_module(_Provider())
    reopened_projects.open_project(root)
    service = reopened_projects.active_project.repository.module_repository("metadata", "indexing_service")

    assert service.progress.total == checkpoint.total_count
    assert service.progress.indexed == checkpoint.indexed_count
    assert service.progress.failed == checkpoint.failed_count
    assert service.state_for("file-1") is MetadataIndexingState.INDEXED
    assert service.changed_at_for("file-1") == checkpoint.entries["file-1"].changed_at
    assert service.dequeue() is None
    assert service.dequeue_completed() is None


def test_module_reclassifies_interrupted_checkpoint_entries_without_persisting(tmp_path):
    manager, projects = _manager_with_module(_Provider())
    root = tmp_path / "interrupted.carvex"
    projects.create_project(ProjectMetadata("Metadata"), JsonProjectStorage(root, create=True))
    store = projects.active_project.repository.module_repository("metadata", "store")
    changed_at = datetime.now(UTC)
    store.save_checkpoint(
        MetadataIndexingCheckpoint(
            1,
            1,
            0,
            1,
            0,
            0,
            {"file-1": MetadataIndexingEntry("file-1", MetadataIndexingState.INDEXING, changed_at)},
        )
    )
    projects.close_project()

    _reopened_manager, reopened_projects = _manager_with_module(_Provider())
    reopened_projects.open_project(root)
    service = reopened_projects.active_project.repository.module_repository("metadata", "indexing_service")
    restored_store = reopened_projects.active_project.repository.module_repository("metadata", "store")

    assert service.state_for("file-1") is MetadataIndexingState.NOT_INDEXED
    assert restored_store.load_checkpoint().entries["file-1"].state is MetadataIndexingState.INDEXING
