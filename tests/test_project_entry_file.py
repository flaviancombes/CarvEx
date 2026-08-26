"""Compatibilité du fichier d'entrée ``project.carvex``."""

from __future__ import annotations

import json

from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.storage import JsonProjectStorage


def _create_project(root):
    manager = ProjectManager()
    project = manager.create_project(ProjectMetadata("Projet entrée"), JsonProjectStorage(root, create=True))
    manager.close_project()
    return project


def test_new_project_creates_its_official_entry_file(tmp_path):
    root = tmp_path / "new.carvex"

    _create_project(root)

    entry = root / JsonProjectStorage.ENTRY_FILE_NAME
    assert entry.is_file()
    assert json.loads(entry.read_text(encoding="utf-8")) == {
        "format": JsonProjectStorage.ENTRY_FORMAT,
        "entry_version": JsonProjectStorage.ENTRY_VERSION,
        "storage": JsonProjectStorage.FILE_NAME,
    }


def test_legacy_project_opens_and_receives_an_entry_file(tmp_path):
    root = tmp_path / "legacy.carvex"
    _create_project(root)
    entry = root / JsonProjectStorage.ENTRY_FILE_NAME
    entry.unlink()

    manager = ProjectManager()
    project = manager.open_project(root)

    assert project.metadata.name == "Projet entrée"
    assert entry.is_file()
    manager.close_project()


def test_project_opens_via_its_entry_file(tmp_path):
    root = tmp_path / "entry-file.carvex"
    _create_project(root)

    manager = ProjectManager()
    project = manager.open_project(root / JsonProjectStorage.ENTRY_FILE_NAME)

    assert project.metadata.name == "Projet entrée"
    manager.close_project()


def test_project_opens_via_its_parent_directory(tmp_path):
    root = tmp_path / "parent-directory.carvex"
    _create_project(root)

    manager = ProjectManager()
    project = manager.open_project(root)

    assert project.metadata.name == "Projet entrée"
    manager.close_project()
