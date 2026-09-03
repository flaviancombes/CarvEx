"""Régressions de la fermeture projet sans sérialisation redondante."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ModuleDescriptor, ProjectModule, ProjectModuleContext, ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage
from ui.main_window import MainWindow
from ui.project_session_controller import ProjectSessionController
from ui.project_workflow_controller import ProjectWorkflowController


class _CountingJsonStorage(JsonProjectStorage):
    def __init__(self, root, *, create: bool = False) -> None:
        super().__init__(root, create=create)
        self.full_flush_count = 0

    def flush(self) -> None:
        was_dirty = self.is_dirty or not self._file.is_file()
        super().flush()
        self.full_flush_count += was_dirty


class _IdempotentSaveModule(ProjectModule):
    """Reproduit un module qui réécrit son état inchangé à la fermeture."""

    @property
    def descriptor(self) -> ModuleDescriptor:
        return ModuleDescriptor(module_id="idempotent", schema_version=1, store_names=frozenset({"state"}))

    def initialize(self, context: ProjectModuleContext) -> None:
        context.store("state").set("value", "stable")

    def save(self, context: ProjectModuleContext) -> None:
        context.store("state").set("value", "stable")


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def test_clean_project_close_does_not_serialize_the_json_payload(tmp_path) -> None:
    storage = _CountingJsonStorage(tmp_path / "clean.carvex", create=True)
    manager = ProjectManager()
    project = manager.create_project(ProjectMetadata("Fermeture"), storage)
    storage.full_flush_count = 0
    # Reproduit la capture du workspace sans changement de disposition réel.
    manager.save_workspace(project.workspaces[project.state.active_workspace_id])

    manager.close_project(save=True)

    assert storage.full_flush_count == 0
    assert not storage.is_dirty
    assert not (storage.root / ".carvex.lock").exists()


def test_dirty_project_close_performs_one_json_serialization(tmp_path) -> None:
    storage = _CountingJsonStorage(tmp_path / "dirty.carvex", create=True)
    manager = ProjectManager()
    project = manager.create_project(ProjectMetadata("Fermeture"), storage)
    storage.full_flush_count = 0
    manager.update_metadata(replace(project.metadata, description="modifiée"))

    manager.close_project(save=True)

    assert storage.full_flush_count == 1
    assert not storage.is_dirty


def test_explicit_save_then_clean_close_does_not_serialize_again(tmp_path) -> None:
    storage = _CountingJsonStorage(tmp_path / "saved.carvex", create=True)
    manager = ProjectManager()
    project = manager.create_project(ProjectMetadata("Fermeture"), storage)
    storage.full_flush_count = 0
    manager.update_metadata(replace(project.metadata, description="modifiée"))

    manager.save_project()
    manager.close_project(save=True)

    assert storage.full_flush_count == 1


def test_opening_and_closing_an_existing_clean_project_do_not_serialize_it(tmp_path) -> None:
    root = tmp_path / "reopen.carvex"
    first_storage = _CountingJsonStorage(root, create=True)
    first = ProjectManager()
    first.create_project(ProjectMetadata("Fermeture"), first_storage)
    first.close_project()
    storage = _CountingJsonStorage(root)
    second = ProjectManager()

    second.open_repository(ProjectRepository(storage))
    second.close_project()

    assert storage.full_flush_count == 0


def test_identical_module_save_does_not_trigger_json_encoding(tmp_path, monkeypatch) -> None:
    registry = ProjectModuleRegistry()
    registry.register(_IdempotentSaveModule())
    storage = _CountingJsonStorage(tmp_path / "module-save.carvex", create=True)
    manager = ProjectManager(registry)
    manager.create_project(ProjectMetadata("Fermeture"), storage)
    storage.full_flush_count = 0

    monkeypatch.setattr("project.storage._encode", lambda *_args: pytest.fail("JSON encoding must be skipped"))

    manager.close_project(save=True)

    assert storage.full_flush_count == 0
    assert not storage.is_dirty


def test_stable_workspace_capture_after_reopen_does_not_serialize_json(tmp_path) -> None:
    application = _application()
    root = tmp_path / "workspace.carvex"

    first_storage = _CountingJsonStorage(root, create=True)
    first_window = MainWindow()
    first_window.show()
    application.processEvents()
    first_project = first_window.project_manager.create_project(ProjectMetadata("Fermeture"), first_storage)
    first_window._attach_project(first_project, str(root))
    first_window._capture_workspace()
    first_window.investigation_panel.detach()
    first_window.project_manager.close_project()
    first_window.close()

    storage = _CountingJsonStorage(root)
    window = MainWindow()
    window.show()
    application.processEvents()
    project = window.project_manager.open_repository(ProjectRepository(storage))
    window._attach_project(project, str(root))
    application.processEvents()
    storage.full_flush_count = 0

    window._capture_workspace()
    window.investigation_panel.detach()
    window.project_manager.close_project()
    window.close()

    assert storage.full_flush_count == 0


def test_unconfigured_default_workspace_does_not_dirty_a_clean_project_on_close(tmp_path, monkeypatch) -> None:
    application = _application()
    root = tmp_path / "default-workspace.carvex"
    storage = _CountingJsonStorage(root, create=True)
    window = MainWindow()
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Fermeture"), storage)
    window._attach_project(project, str(root))
    application.processEvents()
    storage.full_flush_count = 0
    monkeypatch.setattr("project.storage._encode", lambda *_args: pytest.fail("JSON encoding must be skipped"))

    # Le workspace vierge correspond aux valeurs Qt restaurées par défaut :
    # sa capture ne doit pas matérialiser une représentation redondante.
    window._capture_workspace()
    assert not storage.is_dirty
    assert project.workspaces["default"].splitter_sizes == ()

    window.investigation_panel.detach()
    window.project_manager.close_project()
    window.close()

    assert storage.full_flush_count == 0


def test_changed_workspace_is_persisted_once_during_clean_project_close(tmp_path) -> None:
    application = _application()
    root = tmp_path / "changed-workspace.carvex"
    storage = _CountingJsonStorage(root, create=True)
    window = MainWindow()
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Fermeture"), storage)
    window._attach_project(project, str(root))
    application.processEvents()
    storage.full_flush_count = 0

    window.file_table.search_field.setText("preuve")
    window._capture_workspace()
    assert not storage.is_dirty
    assert project.workspaces["default"].searches_by_view["files_view"] == "preuve"

    # Reproduit exactement shutdown.persist_core : une vraie modification du
    # workspace devient dirty à cet instant et est sauvegardée une seule fois.
    project.repository.save_workspace(project.workspaces["default"])
    assert storage.is_dirty
    assert storage.dirty_details()[1] == ("workspaces",)

    window.investigation_panel.detach()
    window.project_manager.close_project()
    window.close()

    assert storage.full_flush_count == 1
    assert not storage.is_dirty


def _configured_workspace(window, project):
    controller = window._workspace_controller
    workspace = replace(
        controller._workspace_from_ui(project.workspaces["default"]),
        splitter_sizes=(806, 475),
    )
    window.project_manager.save_workspace(workspace)
    project.repository.save_workspace(workspace)
    project.repository.save_state(project.state)
    project.repository.flush()
    controller.restore()
    return workspace


def test_splitter_layout_resize_does_not_dirty_workspace_without_user_move(tmp_path, monkeypatch) -> None:
    application = _application()
    storage = _CountingJsonStorage(tmp_path / "splitter-layout.carvex", create=True)
    window = MainWindow()
    window.resize(1_280, 780)
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Fermeture"), storage)
    window._attach_project(project, str(storage.root))
    application.processEvents()
    window.resize(1_920, 780)
    application.processEvents()
    # Le layout Qt rematérialise les proportions sauvegardées dans un
    # conteneur plus large ; aucune poignée n'est déplacée par l'utilisateur.
    workspace = _configured_workspace(window, project)
    application.processEvents()
    workspace = replace(
        window._workspace_controller._workspace_from_ui(project.workspaces["default"]),
        splitter_sizes=workspace.splitter_sizes,
    )
    window.project_manager.save_workspace(workspace)
    project.repository.save_workspace(workspace)
    project.repository.save_state(project.state)
    project.repository.flush()
    assert tuple(window.content_splitter.sizes()) != workspace.splitter_sizes
    assert not window._workspace_controller._splitter_was_moved_by_user
    assert not storage.is_dirty, storage.dirty_details()

    storage.full_flush_count = 0
    monkeypatch.setattr("project.storage._encode", lambda *_args: pytest.fail("JSON encoding must be skipped"))
    window._capture_workspace()
    assert project.workspaces["default"].splitter_sizes == workspace.splitter_sizes
    assert not storage.is_dirty

    window.investigation_panel.detach()
    window.project_manager.close_project()
    window.close()

    assert storage.full_flush_count == 0


def test_user_splitter_drag_persists_the_new_workspace_geometry(tmp_path) -> None:
    application = _application()
    storage = _CountingJsonStorage(tmp_path / "splitter-user-move.carvex", create=True)
    window = MainWindow()
    window.resize(1_280, 780)
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Fermeture"), storage)
    window._attach_project(project, str(storage.root))
    application.processEvents()
    workspace = _configured_workspace(window, project)
    application.processEvents()

    handle = window.content_splitter.handle(1)
    center = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseMove(handle, center + QPoint(120, 0), 20)
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center + QPoint(120, 0))
    application.processEvents()

    assert window._workspace_controller._splitter_was_moved_by_user
    assert tuple(window.content_splitter.sizes()) != workspace.splitter_sizes

    window._capture_workspace()
    assert project.workspaces["default"].splitter_sizes == tuple(window.content_splitter.sizes())
    project.repository.save_workspace(project.workspaces["default"])
    assert storage.is_dirty

    window.investigation_panel.detach()
    window.project_manager.close_project()
    window.close()


def test_failed_dirty_close_keeps_the_session_lock(tmp_path, monkeypatch) -> None:
    storage = _CountingJsonStorage(tmp_path / "failure.carvex", create=True)
    manager = ProjectManager()
    project = manager.create_project(ProjectMetadata("Fermeture"), storage)
    manager.update_metadata(replace(project.metadata, description="modifiée"))
    original_write = storage._atomic_write

    def fail_primary(target, payload):
        if target == storage._file:
            raise OSError("flush failure")
        original_write(target, payload)

    monkeypatch.setattr(storage, "_atomic_write", fail_primary)
    with pytest.raises(OSError, match="flush failure"):
        manager.close_project(save=True)

    assert (storage.root / ".carvex.lock").is_dir()


def test_save_choice_closes_once_without_an_explicit_pre_save(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    manager = SimpleNamespace(
        active_project=object(),
        is_dirty=True,
        close_project=lambda *, save: calls.append(("close", save)),
    )
    workflow = ProjectWorkflowController(
        None,
        manager,
        None,
        attach_project=lambda *_args: None,
        clear_project_ui=lambda: None,
        load_report=lambda *_args: None,
        capture_workspace=lambda: calls.append(("capture", None)),
        refresh_ui=lambda: calls.append(("refresh", None)),
        show_status=lambda *_args: None,
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Save)

    assert workflow.prepare_project_change()
    assert calls == [("capture", None), ("close", True)]


def test_finalized_metadata_is_not_flushed_again_during_shutdown() -> None:
    calls: list[str] = []

    class _Indexing:
        progress = SimpleNamespace(indexing=0)
        has_completed = False

        def shutdown(self) -> None:
            calls.append("shutdown")

        def collect_completed(self):
            calls.append("collect")
            return ()

    controller = object.__new__(ProjectSessionController)
    controller._metadata_timer = SimpleNamespace(stop=lambda: calls.append("timer"))
    controller._metadata_indexing = _Indexing()
    controller._metadata_commit = object()
    controller._metadata_correlations_dirty = False
    controller._metadata_manager = SimpleNamespace(set_store_writable=lambda value: calls.append(f"writable={value}"))
    controller._background_tasks = SimpleNamespace(finish_task=lambda *_args, **_kwargs: calls.append("activity"))
    controller._finalize_metadata_indexing = lambda **_kwargs: calls.append("finalize")

    controller._stop_metadata_indexing(object())

    assert calls == ["timer", "shutdown", "collect", "writable=True", "activity"]
