"""Regression coverage for atomic JSON project persistence and recovery."""

from __future__ import annotations

import pytest

from project.codecs import create_core_codec_registry
from project.models import ProjectManifest
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage, ProjectStorageCorruptionError


def _storage(root, *, create: bool = False) -> JsonProjectStorage:
    storage = JsonProjectStorage(root, create=create)
    storage.configure_codecs(create_core_codec_registry())
    return storage


def _two_saved_versions(root) -> JsonProjectStorage:
    storage = _storage(root, create=True)
    storage.write("samples", "value", "first")
    storage.flush()
    storage.write("samples", "value", "second")
    storage.flush()
    return storage


def test_new_project_writes_checksum_and_keeps_existing_project_format(tmp_path) -> None:
    root = tmp_path / "new.carvex"
    storage = _storage(root, create=True)
    storage.write("samples", "value", "first")
    storage.flush()

    assert (root / JsonProjectStorage.FILE_NAME).is_file()
    assert (root / JsonProjectStorage.CHECKSUM_FILE_NAME).is_file()
    assert not (root / JsonProjectStorage.BACKUP_FILE_NAME).exists()
    assert _storage(root).read("samples", "value") == "first"


def test_interruption_before_primary_replacement_preserves_the_previous_document(tmp_path, monkeypatch) -> None:
    root = tmp_path / "interrupted.carvex"
    storage = _storage(root, create=True)
    storage.write("samples", "value", "first")
    storage.flush()
    storage.write("samples", "value", "second")
    original_write = storage._atomic_write

    def interrupt(target, payload) -> None:
        if target == storage._file:
            raise OSError("simulated interruption")
        original_write(target, payload)

    monkeypatch.setattr(storage, "_atomic_write", interrupt)
    with pytest.raises(OSError, match="simulated interruption"):
        storage.flush()

    reopened = _storage(root)
    assert reopened.read("samples", "value") == "first"
    assert not reopened.recovered_from_backup


def test_incomplete_json_recovers_the_previous_valid_backup(tmp_path) -> None:
    root = tmp_path / "incomplete.carvex"
    _two_saved_versions(root)
    (root / JsonProjectStorage.FILE_NAME).write_bytes(b'{"incomplete":')

    reopened = _storage(root)

    assert reopened.recovered_from_backup
    assert reopened.read("samples", "value") == "first"
    assert _storage(root).read("samples", "value") == "first"


def test_invalid_checksum_recovers_the_previous_valid_backup(tmp_path) -> None:
    root = tmp_path / "checksum.carvex"
    _two_saved_versions(root)
    (root / JsonProjectStorage.CHECKSUM_FILE_NAME).write_text("0" * 64, encoding="ascii")

    reopened = _storage(root)

    assert reopened.recovered_from_backup
    assert reopened.read("samples", "value") == "first"


def test_unrecoverable_project_is_rejected_before_codec_decoding(tmp_path) -> None:
    root = tmp_path / "corrupt.carvex"
    root.mkdir()
    (root / JsonProjectStorage.FILE_NAME).write_bytes(b'{"incomplete":')

    with pytest.raises(ProjectStorageCorruptionError, match="Projet corrompu"):
        JsonProjectStorage(root)


def test_legacy_project_without_checksum_opens_and_receives_protection_on_next_save(tmp_path) -> None:
    root = tmp_path / "legacy.carvex"
    storage = _storage(root, create=True)
    storage.write("samples", "value", "legacy")
    storage.flush()
    (root / JsonProjectStorage.CHECKSUM_FILE_NAME).unlink()

    reopened = _storage(root)
    assert reopened.read("samples", "value") == "legacy"
    reopened.write("samples", "next", "protected")
    reopened.flush()

    assert (root / JsonProjectStorage.CHECKSUM_FILE_NAME).is_file()
    assert (root / JsonProjectStorage.BACKUP_FILE_NAME).is_file()
    assert _storage(root).read("samples", "next") == "protected"


def test_flush_does_not_reparse_the_json_payload_it_just_serialized(tmp_path, monkeypatch) -> None:
    root = tmp_path / "validated-in-memory.carvex"
    storage = _storage(root, create=True)
    storage.write("samples", "value", "first")

    def parsing_is_not_a_flush_validation(*_args, **_kwargs):
        raise AssertionError("Le flush ne doit pas reparser son propre JSON.")

    monkeypatch.setattr("project.storage.json.loads", parsing_is_not_a_flush_validation)
    storage.flush()

    assert (root / JsonProjectStorage.FILE_NAME).is_file()


def test_repository_does_not_mark_unchanged_core_data_dirty(tmp_path) -> None:
    root = tmp_path / "unchanged-core.carvex"
    storage = _storage(root, create=True)
    repository = ProjectRepository(storage)
    manifest = ProjectManifest()
    repository.save_manifest(manifest)
    repository.flush()
    payload_before = (root / JsonProjectStorage.FILE_NAME).read_bytes()

    repository.save_manifest(manifest)

    assert not repository.is_dirty
    repository.flush()
    assert (root / JsonProjectStorage.FILE_NAME).read_bytes() == payload_before
