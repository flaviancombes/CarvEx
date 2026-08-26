from bookmarks.service import BookmarkService
from project.bookmarks_module import BookmarksProjectModule
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry


def test_project_manager_creates_module_repository_without_storage_coupling():
    modules = ProjectModuleRegistry()
    modules.register(BookmarksProjectModule())
    manager = ProjectManager(modules)

    project = manager.create_project(ProjectMetadata("Dossier test"))
    repository = project.repository.module_repository("bookmarks", "bookmarks")
    bookmarks = BookmarkService(repository)

    assert project.has_capability("bookmarks")
    assert bookmarks.count() == 0
