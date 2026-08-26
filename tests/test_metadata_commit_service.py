import hashlib
from datetime import UTC, datetime
from threading import Thread

import pytest

from metadata.base import MetadataCategory, MetadataField, MetadataResult
from metadata.codecs import register_metadata_codecs
from metadata.commit import MetadataCommitService
from metadata.indexing import (
    MetadataBatchResult,
    MetadataIndexingCheckpoint,
    MetadataIndexingEntry,
    MetadataIndexingService,
    MetadataIndexingState,
)
from metadata.store import MetadataStore
from project.codecs import create_core_codec_registry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage, JsonProjectStorage
from project.stores import ProjectStore


def _services():
    storage = InMemoryProjectStorage()
    store = MetadataStore(ProjectStore(storage, "fields"), ProjectStore(storage, "index"))
    indexing = MetadataIndexingService(("a",))
    batch = indexing.enqueue(("a",))
    result = MetadataBatchResult(
        batch, (("a", MetadataResult(fields=(MetadataField("x", MetadataCategory.GENERAL, "X", "v", source="t"),))),)
    )
    return store, indexing, result


def test_commit_orders_store_state_then_checkpoint():
    store, indexing, result = _services()
    events = []
    commit = MetadataCommitService(store, indexing, lambda: events.append("checkpoint"))
    commit.commit(result)
    assert store.contains("a") and indexing.state_for("a").value == "indexed" and events == []
    commit.flush_pending()
    assert events == ["checkpoint"]
    assert store.checkpoint.entries["a"].state is MetadataIndexingState.INDEXED


def test_final_flush_reports_checkpoint_store_index_and_project_timings():
    store, indexing, result = _services()
    timings = []
    commit = MetadataCommitService(store, indexing, lambda: None)

    commit.commit(result)
    commit.flush_pending(lambda label, _duration: timings.append(label))

    assert {
        "Génération du Checkpoint",
        "MetadataIndex",
        "MetadataStore / Checkpoint",
        "ProjectRepository.flush / sauvegarde .carvex",
        "MetadataCommitService",
    } <= set(timings)


def test_deferred_commits_materialize_the_full_index_once_at_flush(monkeypatch):
    storage = InMemoryProjectStorage()
    store = MetadataStore(ProjectStore(storage, "fields"), ProjectStore(storage, "index"))
    indexing = MetadataIndexingService(("a", "b"))
    commit = MetadataCommitService(store, indexing, lambda: None)
    snapshot_calls = 0
    original_snapshot = store.index.snapshot

    def count_snapshot():
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_snapshot()

    monkeypatch.setattr(store.index, "snapshot", count_snapshot)
    field = MetadataField("x", MetadataCategory.GENERAL, "X", "v", source="t")
    for file_id in ("a", "b"):
        batch = indexing.enqueue((file_id,))
        commit.commit(MetadataBatchResult(batch, ((file_id, MetadataResult(fields=(field,))),)))

    assert snapshot_calls == 0
    commit.flush_pending()
    assert snapshot_calls == 1


def test_commit_rejects_non_owner_thread():
    store, indexing, result = _services()
    commit = MetadataCommitService(store, indexing, lambda: None)
    errors = []
    thread = Thread(target=lambda: errors.append(pytest.raises(RuntimeError, commit.commit, result)))
    thread.start()
    thread.join()
    assert errors


def test_store_failure_rolls_back_the_new_field_index_checkpoint_and_service_state(monkeypatch):
    store, indexing, result = _services()
    events = []
    original_set = store._fields_store.set
    failed = False

    def fail_after_write(key, value):
        nonlocal failed
        original_set(key, value)
        if not failed:
            failed = True
            raise RuntimeError("store failure")

    monkeypatch.setattr(store._fields_store, "set", fail_after_write)

    with pytest.raises(RuntimeError, match="store failure"):
        MetadataCommitService(store, indexing, lambda: events.append("checkpoint")).commit(result)

    assert store.get("a") is None
    assert store.index.search("v") == frozenset()
    assert store.checkpoint is None
    assert indexing.state_for("a") is MetadataIndexingState.INDEXING
    assert events == []


def test_index_failure_rolls_back_the_exact_preimage(monkeypatch):
    store, indexing, result = _services()
    original_set = store._index_store.set
    failed = False

    def fail_once_for_index(key, value):
        nonlocal failed
        if key == store.INDEX_KEY and not failed:
            failed = True
            raise RuntimeError("index failure")
        original_set(key, value)

    monkeypatch.setattr(store._index_store, "set", fail_once_for_index)

    commit = MetadataCommitService(store, indexing, lambda: None)
    commit.commit(result)
    with pytest.raises(RuntimeError, match="index failure"):
        commit.flush_pending()

    assert store.get("a") is None
    assert store.index.snapshot() == {"category": {}, "source": {}, "value": {}}
    assert store.checkpoint is None
    assert indexing.state_for("a") is MetadataIndexingState.INDEXING


def test_checkpoint_failure_restores_existing_fields_index_and_checkpoint(monkeypatch):
    store, indexing, result = _services()
    existing = MetadataResult(fields=(MetadataField("old", MetadataCategory.GENERAL, "Old", "value", source="t"),))
    store.set("existing", existing)
    changed_at = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    previous_checkpoint = MetadataIndexingCheckpoint(
        1,
        1,
        4,
        1,
        0,
        0,
        {"a": MetadataIndexingEntry("a", MetadataIndexingState.INDEXING, changed_at)},
    )
    store.save_checkpoint(previous_checkpoint)
    previous_index = store.index.snapshot()
    original_set = store._index_store.set
    failed = False

    def fail_once_for_checkpoint(key, value):
        nonlocal failed
        if key == store.CHECKPOINT_KEY and not failed:
            failed = True
            raise RuntimeError("checkpoint failure")
        original_set(key, value)

    monkeypatch.setattr(store._index_store, "set", fail_once_for_checkpoint)

    commit = MetadataCommitService(store, indexing, lambda: None)
    commit.commit(result)
    with pytest.raises(RuntimeError, match="checkpoint failure"):
        commit.flush_pending()

    assert store.get("existing") == existing
    assert store.get("a") is None
    assert store.index.snapshot() == previous_index
    assert store.checkpoint == previous_checkpoint
    assert store.checkpoint.entries["a"].changed_at == changed_at
    assert store.checkpoint.indexed_count == 0
    assert store.checkpoint.failed_count == 0
    assert indexing.state_for("a") is MetadataIndexingState.INDEXING


def test_flush_failure_rolls_back_the_memory_transaction():
    store, indexing, result = _services()

    commit = MetadataCommitService(store, indexing, lambda: (_ for _ in ()).throw(OSError("flush failure")))
    commit.commit(result)
    with pytest.raises(OSError, match="flush failure"):
        commit.flush_pending()

    assert store.get("a") is None
    assert store.index.snapshot() == {"category": {}, "source": {}, "value": {}}
    assert store.checkpoint is None
    assert indexing.state_for("a") is MetadataIndexingState.INDEXING


def test_json_flush_failure_restores_disk_and_a_following_commit_is_consistent(tmp_path, monkeypatch):
    root = tmp_path / "metadata.carvex"
    registry = create_core_codec_registry()
    register_metadata_codecs(registry)
    storage = JsonProjectStorage(root, create=True)
    storage.configure_codecs(registry)
    repository = ProjectRepository(storage)
    store = MetadataStore(
        ProjectStore(storage, "module:metadata:fields"),
        ProjectStore(storage, "module:metadata:index"),
    )
    storage.flush()
    primary_before = (root / "project.json").read_bytes()
    checksum_before = (root / "project.json.sha256").read_bytes()
    indexing = MetadataIndexingService(("a",))
    batch = indexing.enqueue(("a",))
    result = MetadataBatchResult(
        batch,
        (("a", MetadataResult(fields=(MetadataField("x", MetadataCategory.GENERAL, "X", "v", source="t"),))),),
    )
    original_atomic_write = storage._atomic_write
    failed = False

    def fail_once_for_primary_checksum(target, payload):
        nonlocal failed
        if target.name == storage.CHECKSUM_FILE_NAME and not failed:
            failed = True
            raise OSError("checksum flush failure")
        original_atomic_write(target, payload)

    monkeypatch.setattr(storage, "_atomic_write", fail_once_for_primary_checksum)
    commit = MetadataCommitService(store, indexing, repository.flush)
    commit.commit(result)
    with pytest.raises(OSError, match="checksum flush failure"):
        commit.flush_pending()

    assert (root / "project.json").read_bytes() == primary_before
    assert (root / "project.json.sha256").read_bytes() == checksum_before
    backup_payload = (root / "project.json.bak").read_bytes()
    backup_checksum = (root / "project.json.bak.sha256").read_text(encoding="ascii").strip()
    assert hashlib.sha256(backup_payload).hexdigest() == backup_checksum
    assert store.get("a") is None
    assert store.checkpoint is None
    assert indexing.state_for("a") is MetadataIndexingState.INDEXING

    commit = MetadataCommitService(store, indexing, repository.flush)
    commit.commit(result)
    commit.flush_pending()
    reopened = JsonProjectStorage(root)
    reopened.configure_codecs(registry)
    restored_store = MetadataStore(
        ProjectStore(reopened, "module:metadata:fields"),
        ProjectStore(reopened, "module:metadata:index"),
    )

    assert restored_store.get("a") == result.results[0][1]
    assert restored_store.index.search("v") == frozenset({"a"})
    assert restored_store.checkpoint.entries["a"].state is MetadataIndexingState.INDEXED
