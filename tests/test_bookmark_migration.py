"""Compatibilité de lecture des bookmarks Timeline historiques."""

from __future__ import annotations

from datetime import UTC, datetime

from bookmarks.model import Bookmark, BookmarkKey
from bookmarks.repository import InMemoryBookmarkRepository
from bookmarks.service import BookmarkService
from project.bookmarks_module import BookmarksProjectModule
from project.manager import ProjectManager
from project.models import ProjectManifest, ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage


def _manager() -> ProjectManager:
    modules = ProjectModuleRegistry()
    modules.register(BookmarksProjectModule())
    return ProjectManager(modules)


def test_opening_v1_project_migrates_a_legacy_timeline_bookmark_to_its_file_id():
    file_id = "a8b50f48-5a3e-412f-9a94-22d22eac5ed7"
    legacy = Bookmark("timeline_event", f"{file_id}:filesystem.modified:0", datetime.now(UTC))
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(
        ProjectManifest(enabled_modules=frozenset({"bookmarks"}), module_schemas={"bookmarks": 1}),
        ProjectMetadata("Projet historique"),
    )
    repository.store_for("bookmarks", "bookmarks").set("bookmarks", (legacy,))

    manager = _manager()
    project = manager.open_repository(repository)
    bookmarks = BookmarkService(project.repository.module_repository("bookmarks", "bookmarks"))

    assert bookmarks.all()[0].key == BookmarkKey("file", file_id)
    persisted = repository.store_for("bookmarks", "bookmarks").get("bookmarks")
    assert persisted[0].key == BookmarkKey("file", file_id)
    assert project.manifest.module_schemas["bookmarks"] == 2
    assert "module:bookmarks:1->2" in project.manifest.migration_history

    manager.close_project()
    reopened = _manager().open_repository(repository)
    assert reopened.repository.module_repository(
        "bookmarks", "bookmarks"
    ).load().__iter__().__next__().key == BookmarkKey("file", file_id)


def test_unresolvable_legacy_bookmark_is_preserved_without_inventing_a_file_id():
    legacy = Bookmark("timeline_event", "legacy-event-without-file-prefix", datetime.now(UTC))
    repository = InMemoryBookmarkRepository((legacy,))

    service = BookmarkService(repository)

    assert service.count() == 0
    assert tuple(repository.load()) == (legacy,)
