"""Vue passive des bookmarks, connectée au SelectionManager par MainWindow."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMenu, QTableView, QVBoxLayout, QWidget

from bookmarks.qt_model import BookmarkModel
from bookmarks.service import BookmarkService
from selection.canonical_entity_resolver import CanonicalEntityResolver
from ui.bookmark_delegate import BookmarkStarDelegate
from ui.investigation_context_menu import append_investigation_actions


class BookmarksView(QWidget):
    bookmark_selected = Signal(object)
    investigation_item_requested = Signal(object)

    def __init__(
        self, service: BookmarkService, parent=None, entity_resolver: CanonicalEntityResolver | None = None
    ) -> None:
        super().__init__(parent)
        self._model = BookmarkModel(service, self, entity_resolver)
        self._investigation_presence_lookup: Callable[[object], bool] | None = None
        self.table = QTableView(self)
        self.table.setModel(self._model)
        self.table.setItemDelegateForColumn(BookmarkModel.BOOKMARK_COLUMN, BookmarkStarDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.table.setColumnWidth(0, 38)
        self.table.setColumnWidth(BookmarkModel.INVESTIGATION_COLUMN, 32)
        self.table.selectionModel().currentRowChanged.connect(self._select_index)
        self.table.clicked.connect(lambda index: self._select_index(index, QModelIndex()))
        self._copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.table)
        self._copy_shortcut.activated.connect(self._copy_selection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

    def _select_index(self, current: QModelIndex, _previous: QModelIndex) -> None:
        bookmark = self._model.bookmark_at(current.row()) if current.isValid() else None
        if bookmark is not None:
            self.bookmark_selected.emit(bookmark)

    def set_investigation_presence_lookup(self, lookup: Callable[[object], bool] | None) -> None:
        self._investigation_presence_lookup = lookup
        self._model.set_investigation_lookup(lookup)

    def refresh_investigation_markers(self, file_ids: Iterable[str]) -> None:
        """Actualise les seuls bookmarks canoniques associés aux fichiers modifiés."""
        self._model.refresh_investigation_markers(file_ids)

    def refresh_file_projection(self) -> None:
        self._model.refresh_file_projection()

    def _copy_selection(self) -> None:
        index = self.table.currentIndex()
        if index.isValid():
            from PySide6.QtWidgets import QApplication

            value = (
                self._model.data(self._model.index(index.row(), 1))
                if index.column()
                in {
                    BookmarkModel.BOOKMARK_COLUMN,
                    BookmarkModel.INVESTIGATION_COLUMN,
                }
                else index.data(Qt.ItemDataRole.DisplayRole)
            )
            QApplication.clipboard().setText(str(value or ""))

    def _show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        bookmark = self._model.bookmark_at(index.row()) if index.isValid() else None
        if bookmark is None:
            return
        self.table.setCurrentIndex(index)
        self._context_menu_for_bookmark(bookmark).exec(self.table.viewport().mapToGlobal(position))

    def _context_menu_for_bookmark(self, bookmark) -> QMenu:
        menu = QMenu(self.table)
        append_investigation_actions(
            menu,
            is_present=bool(self._investigation_presence_lookup and self._investigation_presence_lookup(bookmark)),
            edit_evidence=lambda: self.investigation_item_requested.emit(bookmark),
        )
        return menu
