from datetime import UTC, datetime

import pytest

from metadata.codecs import register_metadata_codecs
from metadata.indexing import MetadataIndexingCheckpoint, MetadataIndexingEntry, MetadataIndexingState
from project.codecs import ProjectCodecRegistry
from project.storage import JsonProjectStorage


def _checkpoint() -> MetadataIndexingCheckpoint:
    entry = MetadataIndexingEntry("file-1", MetadataIndexingState.INDEXED, datetime.now(UTC))
    return MetadataIndexingCheckpoint(1, 1, 0, 1, 1, 0, {"file-1": entry})


def test_checkpoint_is_immutable_and_timezone_aware():
    checkpoint = _checkpoint()
    with pytest.raises(TypeError):
        checkpoint.entries["other"] = checkpoint.entries["file-1"]
    with pytest.raises(ValueError):
        MetadataIndexingEntry("file", MetadataIndexingState.FAILED, datetime.now())
    with pytest.raises(ValueError):
        MetadataIndexingEntry("file", "invalid", datetime.now(UTC))  # type: ignore[arg-type]


def test_checkpoint_rejects_incompatible_schema_and_invalid_counts():
    with pytest.raises(ValueError):
        MetadataIndexingCheckpoint(2, 1, 0, 0, 0, 0, {})
    with pytest.raises(ValueError):
        MetadataIndexingCheckpoint(1, 1, 0, 1, 1, 0, {})


def test_checkpoint_codecs_register_and_roundtrip_model_payload():
    registry = ProjectCodecRegistry()
    register_metadata_codecs(registry)
    checkpoint = _checkpoint()
    type_id, payload = registry.serialize(checkpoint)
    restored = registry.deserialize(type_id, payload)
    assert restored == checkpoint
    assert MetadataIndexingCheckpoint.CURRENT_SCHEMA_VERSION == 1


def test_checkpoint_roundtrips_through_json_storage_with_aware_datetime(tmp_path):
    root = tmp_path / "case.carvex"
    registry = ProjectCodecRegistry()
    register_metadata_codecs(registry)
    checkpoint = _checkpoint()
    storage = JsonProjectStorage(root, create=True)
    storage.configure_codecs(registry)
    storage.write("metadata", "indexing_checkpoint", checkpoint)
    storage.flush()

    reopened = JsonProjectStorage(root)
    reopened.configure_codecs(registry)
    restored = reopened.read("metadata", "indexing_checkpoint")

    assert restored == checkpoint
    assert restored.entries["file-1"].changed_at.tzinfo is not None


def test_project_without_checkpoint_remains_readable(tmp_path):
    root = tmp_path / "legacy.carvex"
    registry = ProjectCodecRegistry()
    register_metadata_codecs(registry)
    storage = JsonProjectStorage(root, create=True)
    storage.configure_codecs(registry)
    storage.flush()

    reopened = JsonProjectStorage(root)
    reopened.configure_codecs(registry)
    assert reopened.read("metadata", "indexing_checkpoint") is None
