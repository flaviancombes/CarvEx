"""Non-regression coverage for exclusive project access."""

from __future__ import annotations

import json
import socket

import pytest

from project.locking import ProjectLock, ProjectLockedError
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.storage import JsonProjectStorage


def _create_project(root):
    manager = ProjectManager()
    manager.create_project(ProjectMetadata("Projet verrouillé"), JsonProjectStorage(root, create=True))
    return manager


def test_second_project_manager_is_refused_while_the_first_holds_the_lock(tmp_path) -> None:
    root = tmp_path / "locked.carvex"
    first = _create_project(root)

    with pytest.raises(ProjectLockedError, match="déjà ouvert"):
        ProjectManager().open_project(root)

    first.close_project()


def test_lock_is_released_on_normal_project_close(tmp_path) -> None:
    root = tmp_path / "closed.carvex"
    first = _create_project(root)
    first.close_project()

    second = ProjectManager()
    second.open_project(root)

    assert second.active_project is not None
    second.close_project()


def test_dead_local_lock_is_reclaimed_without_deleting_project_data(tmp_path) -> None:
    root = tmp_path / "abandoned.carvex"
    root.mkdir()
    lock_directory = root / ProjectLock.DIRECTORY_NAME
    lock_directory.mkdir()
    (lock_directory / ProjectLock.OWNER_FILE_NAME).write_text(
        json.dumps(
            {
                "hostname": socket.gethostname(),
                "pid": 999_999_999,
                "acquired_at": "2026-01-01T00:00:00+00:00",
                "token": "abandoned",
            }
        ),
        encoding="utf-8",
    )

    manager = _create_project(root)

    assert manager.active_project is not None
    assert lock_directory.is_dir()
    manager.close_project()
    assert not lock_directory.exists()


def test_invalid_or_remote_lock_is_never_reclaimed_automatically(tmp_path) -> None:
    root = tmp_path / "unsafe.carvex"
    root.mkdir()
    lock_directory = root / ProjectLock.DIRECTORY_NAME
    lock_directory.mkdir()
    (lock_directory / ProjectLock.OWNER_FILE_NAME).write_text("not-json", encoding="utf-8")

    with pytest.raises(ProjectLockedError, match="métadonnées invalides"):
        _create_project(root)

    assert lock_directory.is_dir()


def test_lock_directory_can_be_removed_after_a_crash_recovery(tmp_path) -> None:
    root = tmp_path / "removed.carvex"
    first = _create_project(root)
    first.close_project()

    lock_directory = root / ProjectLock.DIRECTORY_NAME
    assert not lock_directory.exists()
    second = ProjectManager()
    second.open_project(root)

    assert second.active_project is not None
    second.close_project()
