"""Non-régression : persistance workspace pour InvestigationTreeView."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView, QTableView, QTreeView

from project.models import ProjectMetadata, Workspace
from timeline.model import TimelineTableModel
from ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def test_workspace_header_helper_supports_tables_and_investigation_tree():
    _application()
    window = MainWindow()

    assert isinstance(window._view_header(window.file_table.view), QHeaderView)
    assert isinstance(window.file_table.view, QTableView)
    assert isinstance(window.investigation_panel.tree, QTreeView)
    assert window._view_header(window.investigation_panel.tree) is window.investigation_panel.tree.header()
    assert window._column_order(window.investigation_panel.tree) == (0,)
    assert window._sort_state(window.investigation_panel.tree)[1] in {"ascending", "descending"}


def test_workspace_capture_and_restore_preserve_investigation_tree_header_state():
    _application()
    window = MainWindow()
    project = window.project_manager.create_project(ProjectMetadata("Workspace Investigation"))
    window._attach_project(project, "")
    tree = window.investigation_panel.tree
    header = tree.header()
    header.resizeSection(0, 240)
    header.setSectionHidden(0, True)
    window.main_tabs.setCurrentIndex(3)

    window._capture_workspace()
    workspace = project.workspaces[project.state.active_workspace_id]

    assert workspace.active_tab == "investigation_view"
    assert workspace.columns_by_view["investigation_view"] == (0,)
    assert "investigation_view" in workspace.header_states
    assert "investigation_view" in workspace.sort_by_view

    header.setSectionHidden(0, False)
    header.resizeSection(0, 80)
    window.main_tabs.setCurrentIndex(0)
    window._restore_workspace()

    assert window.main_tabs.currentIndex() == 3
    assert header.isSectionHidden(0)
    window.investigation_panel.detach()
    window.project_manager.close_project()


def test_details_splitter_keeps_a_usable_panel_when_resized_or_restored():
    application = _application()
    window = MainWindow()
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Workspace Details"))
    window._attach_project(project, "")
    window.details_panel.setVisible(True)
    application.processEvents()
    splitter = window.content_splitter
    minimum_width = window.details_panel.minimumWidth()

    assert minimum_width == 360
    assert not splitter.isCollapsible(1)
    assert splitter.sizes()[1] >= minimum_width

    splitter.setSizes([1_200, 1])
    assert splitter.sizes()[1] >= minimum_width

    splitter.setSizes([720, 520])
    window._capture_workspace()
    splitter.setSizes([1_200, 1])

    window._restore_workspace()

    assert splitter.sizes()[1] >= minimum_width
    window.investigation_panel.detach()
    window.project_manager.close_project()


def test_workspace_shows_details_by_default_and_remembers_a_voluntary_hide():
    application = _application()
    window = MainWindow()
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Workspace Details Visibility"))
    project.workspaces["default"] = Workspace("default", "Espace principal")

    window._attach_project(project, "")
    application.processEvents()

    assert window.details_panel.isVisible()

    window.details_panel.hide()
    window._capture_workspace()
    workspace = project.workspaces[project.state.active_workspace_id]
    assert "details_visibility_saved" in workspace.opened_panels
    assert "details" not in workspace.opened_panels

    window.details_panel.show()
    window._restore_workspace()

    assert not window.details_panel.isVisible()
    window.investigation_panel.detach()
    window.project_manager.close_project()


def test_workspace_migrates_the_timeline_selection_column_and_sort_state():
    application = _application()
    window = MainWindow()
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Workspace Timeline Columns"))
    header = window.timeline_view.table.header()
    header.setFirstSectionMovable(True)
    header.moveSection(0, 5)
    legacy_header_state = bytes(header.saveState())
    project.workspaces["default"] = Workspace(
        "default",
        "Espace principal",
        header_states={"timeline_view": legacy_header_state},
        sort_by_view={"timeline_view": (9, "descending")},
        filters_by_view={"timeline_view": {}},
    )

    window._attach_project(project, "")
    application.processEvents()

    assert window.timeline_view.table.header().visualIndex(TimelineTableModel.SELECTION_COLUMN) == 0
    assert window.timeline_view._pending_sort_state == (0, Qt.SortOrder.DescendingOrder)

    window._capture_workspace()
    workspace = project.workspaces[project.state.active_workspace_id]
    assert workspace.filters_by_view["timeline_view"]["column_layout_version"] == "2"
    assert workspace.columns_by_view["timeline_view"][TimelineTableModel.SELECTION_COLUMN] == 0
    window.investigation_panel.detach()
    window.project_manager.close_project()


def test_workspace_neutralizes_a_historic_files_selection_sort():
    application = _application()
    window = MainWindow()
    window.show()
    application.processEvents()
    project = window.project_manager.create_project(ProjectMetadata("Workspace Files Selection Sort"))
    project.workspaces["default"] = Workspace(
        "default",
        "Espace principal",
        sort_by_view={"files_view": (0, "descending")},
    )

    window._attach_project(project, "")
    application.processEvents()

    assert window.file_table._proxy_model.sortColumn() == -1
    assert window.file_table.view.horizontalHeader().sortIndicatorSection() == -1
    window.investigation_panel.detach()
    window.project_manager.close_project()
