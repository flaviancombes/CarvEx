"""Explorateur de fichiers : recherche, filtres et tableau Qt."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from models.file_table_model import FileTableModel
from ui.file_actions import FileActions
from ui.file_filter_proxy import FileFilterProxyModel


class FileTable(QWidget):
    """Widget MVC pour parcourir efficacement les fichiers d'un rapport."""

    record_selected = Signal(object)
    status_message = Signal(str)
    view_state_changed = Signal(str, int)

    CATEGORY_FILTERS = (
        ("Tous", "", "Tous"),
        ("📄 Documents", "Documents", "Documents"),
        ("🖼 Images", "Images", "Images"),
        ("📜 Code", "Code", "Code"),
        ("🗜 Archives", "Archives", "Archives"),
        ("💾 Bases de données", "Databases", "Bases de données"),
        ("❓ Unknown", "Unknown", "Unknown"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fileTable")
        self._source_model = FileTableModel(parent=self)
        self._proxy_model = FileFilterProxyModel(parent=self)
        self._proxy_model.setSourceModel(self._source_model)
        self._shortcuts: list[QShortcut] = []
        self.file_actions = FileActions(self)
        self.file_actions.status_message.connect(self.status_message)

        self.search_field = QLineEdit(self)
        self.search_field.setPlaceholderText("Rechercher un nom, hash, type ou chemin…")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._set_search_text)

        filters = self._create_filters()
        self.view = QTableView(self)
        self.view.setModel(self._proxy_model)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setWordWrap(False)
        self.view.setSortingEnabled(True)
        self.view.verticalHeader().setVisible(False)
        self.view.selectionModel().currentRowChanged.connect(self._emit_selected_record)
        self.view.doubleClicked.connect(self._open_file_at_index)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        self._create_shortcuts()

        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.view.setColumnWidth(0, 260)
        self.view.setColumnWidth(1, 140)
        self.view.setColumnWidth(2, 190)
        self.view.setColumnWidth(3, 100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.search_field)
        layout.addWidget(filters)
        layout.addWidget(self.view, 1)

    def _create_filters(self) -> QWidget:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        for label, category, category_label in self.CATEGORY_FILTERS:
            button = QToolButton(container)
            button.setText(label)
            button.setCheckable(True)
            button.setProperty("category", category)
            button.setProperty("category_label", category_label)
            self.category_group.addButton(button)
            layout.addWidget(button)
            if not category:
                button.setChecked(True)
        layout.addStretch()
        self.category_group.idClicked.connect(self._apply_category_filter)
        return container

    def _apply_category_filter(self, button_id: int) -> None:
        button = self.category_group.button(button_id)
        self._proxy_model.set_category(str(button.property("category")))
        self._emit_view_state()

    def _set_search_text(self, text: str) -> None:
        self._proxy_model.set_search_text(text)
        self._emit_view_state()

    def _emit_view_state(self) -> None:
        button = self.category_group.checkedButton()
        category = str(button.property("category_label")) if button else "Tous"
        self.view_state_changed.emit(category, self._proxy_model.rowCount())

    def _emit_selected_record(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.record_selected.emit(self.record_for_index(current))

    def _create_shortcuts(self) -> None:
        self._shortcut(QKeySequence("Return"), self._open_current_file)
        self._shortcut(QKeySequence("Enter"), self._open_current_file)
        self._shortcut(QKeySequence("Ctrl+O"), self._open_current_file)
        self._shortcut(QKeySequence("Ctrl+Shift+O"), self._open_current_folder)
        self._shortcut(QKeySequence("Ctrl+C"), lambda: self._copy_current("sha256", "SHA-256"))
        self._shortcut(QKeySequence("Ctrl+Shift+C"), lambda: self._copy_current("output", "Chemin exporté"))

    def _shortcut(self, sequence: QKeySequence, callback) -> None:
        shortcut = QShortcut(sequence, self.view)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)

    def _show_context_menu(self, position: QPoint) -> None:
        index = self.view.indexAt(position)
        if not index.isValid():
            return
        self.view.setCurrentIndex(index)
        record = self.record_for_index(index)
        if record is not None:
            self.file_actions.create_context_menu(record, self.view).exec(
                self.view.viewport().mapToGlobal(position)
            )

    def _open_file_at_index(self, index: QModelIndex) -> None:
        record = self.record_for_index(index)
        if record is not None:
            self.file_actions.open_file(record, self.window())

    def _open_current_file(self) -> None:
        self._open_file_at_index(self.view.currentIndex())

    def _open_current_folder(self) -> None:
        record = self.record_for_index(self.view.currentIndex())
        if record is not None:
            self.file_actions.open_containing_folder(record, self.window())

    def _copy_current(self, field: str, label: str) -> None:
        record = self.record_for_index(self.view.currentIndex())
        if record is not None:
            self.file_actions.copy_value(record, field, label)

    @property
    def file_count(self) -> int:
        return self._source_model.rowCount()

    @property
    def visible_file_count(self) -> int:
        """Retourne le nombre de lignes actuellement exposées par le proxy Qt."""
        return self._proxy_model.rowCount()

    def set_files(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Affiche les enregistrements backend sans les dupliquer."""
        self._source_model.set_records(records)
        self._proxy_model.invalidateFilter()
        self._emit_view_state()

    def record_for_index(self, index: QModelIndex) -> Mapping[str, Any] | None:
        """Récupère l'enregistrement source complet à partir d'un index proxy."""
        if not index.isValid():
            return None
        source_index = self._proxy_model.mapToSource(index)
        return self._source_model.record_at(source_index.row())
