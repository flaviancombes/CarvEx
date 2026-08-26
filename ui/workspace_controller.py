"""Persistance de l'état Qt des vues d'un workspace, hors MainWindow."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QTableView, QTreeView

from project.models import Workspace


class WorkspaceController:
    """Capture et restaure l'état visuel sans connaître le cycle de vie du projet."""

    _TAB_IDS = ("files_view", "timeline_view", "bookmarks_view", "investigation_view")
    _DEFAULT_SPLITTER_SIZES = (780, 460)
    _DETAILS_VISIBILITY_SAVED = "details_visibility_saved"
    _TIMELINE_LAYOUT_VERSION = "2"
    _LEGACY_TIMELINE_COLUMNS = {0: 8, 8: 9, 9: 0}

    def __init__(
        self,
        project_manager,
        splitter,
        tabs,
        file_table,
        timeline_view,
        bookmarks_view,
        investigation_panel,
        details_panel,
    ) -> None:
        self._project_manager = project_manager
        self._splitter = splitter
        self._tabs = tabs
        self._file_table = file_table
        self._timeline_view = timeline_view
        self._bookmarks_view = bookmarks_view
        self._investigation_panel = investigation_panel
        self._details_panel = details_panel

    def capture(self) -> None:
        project = self._project_manager.active_project
        if project is None:
            return
        current = project.workspaces.get(project.state.active_workspace_id, Workspace("default", "Espace principal"))
        workspace = replace(
            current,
            active_tab=self._TAB_IDS[self._tabs.currentIndex()],
            splitter_sizes=tuple(self._splitter.sizes()),
            header_states={view_id: bytes(self.view_header(view).saveState()) for view_id, view in self.views()},
            columns_by_view={view_id: self.column_order(view) for view_id, view in self.views()},
            sort_by_view={view_id: self.sort_state(view) for view_id, view in self.views()},
            filters_by_view={
                "files_view": {
                    "category": (
                        str(self._file_table.category_group.checkedButton().property("category") or "")
                        if self._file_table.category_group.checkedButton()
                        else ""
                    ),
                    "artifact": str(self._file_table.artifact_filter.currentData() or ""),
                    **self._file_table.workspace_state(),
                    "metadata_expanded": ",".join(self._details_panel.metadata_panel.expanded_categories()),
                    "correlations_expanded": ",".join(self._details_panel.correlation_panel.expanded_types()),
                },
                "timeline_view": {
                    "category": str(self._timeline_view.category.currentData() or ""),
                    "event_type": str(self._timeline_view.event_type.currentData() or ""),
                    "grouping": "Fichier",
                    "column_layout_version": self._TIMELINE_LAYOUT_VERSION,
                },
            },
            opened_panels=frozenset(
                {
                    self._DETAILS_VISIBILITY_SAVED,
                    *(
                        name
                        for name, visible in {
                            "details": self._details_panel.isVisible(),
                            "metadata": self._details_panel.metadata_panel.isVisible(),
                        }.items()
                        if visible
                    ),
                }
            ),
            searches_by_view={
                "files_view": self._file_table.search_field.text(),
                "timeline_view": self._timeline_view.search.text(),
            },
        )
        self._project_manager.workspace_manager.save(workspace)

    def restore(self) -> None:
        project = self._project_manager.active_project
        if project is None:
            return
        workspace = project.workspaces.get(project.state.active_workspace_id)
        splitter_sizes = (
            workspace.splitter_sizes
            if workspace is not None and workspace.splitter_sizes
            else self._DEFAULT_SPLITTER_SIZES
        )
        self._restore_splitter_sizes(splitter_sizes)
        if workspace is None:
            return
        legacy_timeline_layout = (
            workspace.filters_by_view.get("timeline_view", {}).get("column_layout_version")
            != self._TIMELINE_LAYOUT_VERSION
        )
        for view_id, view in self.views():
            if state := workspace.header_states.get(view_id):
                self.view_header(view).restoreState(state)
            if view_id == "timeline_view":
                self._timeline_view.ensure_selection_column_first()
        self._restore_filters(workspace)
        self._restore_sorting(workspace, legacy_timeline_layout)
        self._tabs.setCurrentIndex(
            self._TAB_IDS.index(workspace.active_tab) if workspace.active_tab in self._TAB_IDS else 0
        )

    def _restore_splitter_sizes(self, sizes: tuple[int, ...]) -> None:
        self._splitter.setSizes(list(sizes))
        QTimer.singleShot(0, lambda: self._splitter.setSizes(list(sizes)))

    @staticmethod
    def view_header(view):
        if isinstance(view, QTreeView):
            return view.header()
        if isinstance(view, QTableView):
            return view.horizontalHeader()
        raise TypeError(f"Vue non prise en charge pour le workspace : {type(view).__name__}")

    def views(self):
        return (
            ("files_view", self._file_table.view),
            ("timeline_view", self._timeline_view.table),
            ("bookmarks_view", self._bookmarks_view.table),
            ("investigation_view", self._investigation_panel.tree),
        )

    @classmethod
    def sort_state(cls, view) -> tuple[int, str]:
        header = cls.view_header(view)
        return header.sortIndicatorSection(), (
            "descending" if header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder else "ascending"
        )

    @classmethod
    def column_order(cls, view) -> tuple[int, ...]:
        header = cls.view_header(view)
        return tuple(header.visualIndex(column) for column in range(header.count()))

    def _restore_filters(self, workspace: Workspace) -> None:
        file_filters = workspace.filters_by_view.get("files_view", {})
        for button in self._file_table.category_group.buttons():
            if str(button.property("category") or "") == file_filters.get("category", ""):
                button.setChecked(True)
                self._file_table._apply_category_filter(self._file_table.category_group.id(button))
                break
        self._select_combo_data(self._file_table.artifact_filter, file_filters.get("artifact", ""))
        self._file_table.search_field.setText(workspace.searches_by_view.get("files_view", ""))
        self._file_table.restore_workspace_state(dict(file_filters))
        self._details_panel.metadata_panel.restore_expanded_categories(
            tuple(filter(None, file_filters.get("metadata_expanded", "").split(",")))
        )
        self._details_panel.correlation_panel.restore_expanded_types(
            tuple(filter(None, file_filters.get("correlations_expanded", "").split(",")))
        )
        details_visible = (
            "details" in workspace.opened_panels if self._DETAILS_VISIBILITY_SAVED in workspace.opened_panels else True
        )
        self._details_panel.setVisible(details_visible)
        timeline_filters = workspace.filters_by_view.get("timeline_view", {})
        self._timeline_view.restore_filter_state(
            workspace.searches_by_view.get("timeline_view", ""),
            timeline_filters.get("category", ""),
            timeline_filters.get("event_type", ""),
            timeline_filters.get("grouping", ""),
        )

    @staticmethod
    def _select_combo_data(combo, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _restore_sorting(self, workspace: Workspace, legacy_timeline_layout: bool = False) -> None:
        for view_id, view in self.views():
            state = workspace.sort_by_view.get(view_id)
            if state is None:
                continue
            column, order = state
            qt_order = Qt.SortOrder.DescendingOrder if order == "descending" else Qt.SortOrder.AscendingOrder
            if view_id == "timeline_view":
                if legacy_timeline_layout:
                    column = self._LEGACY_TIMELINE_COLUMNS.get(column, column)
                self._timeline_view.restore_sort_state(column, qt_order)
            elif view_id == "files_view":
                self._file_table.restore_sort_state(column, qt_order)
            elif isinstance(view, QTableView):
                view.sortByColumn(column, qt_order)
            elif isinstance(view, QTreeView) and view.isSortingEnabled():
                view.sortByColumn(column, qt_order)
