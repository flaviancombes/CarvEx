"""Panneau DFIR de consultation des métadonnées déjà mises en cache."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QTreeView, QVBoxLayout

from core.file_identity import FileIdentityError
from metadata.base import MetadataResult
from metadata.cache import MetadataCache
from metadata.manager import MetadataManager
from ui.metadata_model import MetadataTreeModel
from ui.theme import Metrics


class MetadataPanel(QGroupBox):
    """Affiche exclusivement le résultat présent dans ``MetadataCache``."""

    def __init__(self, cache: MetadataCache, parent=None, manager: MetadataManager | None = None) -> None:
        super().__init__("Métadonnées", parent)
        self._cache = cache
        self._manager = manager
        layout = QVBoxLayout(self)
        layout.setSpacing(Metrics.PANEL_SPACING)
        header = QHBoxLayout()
        self.indicators = QLabel(self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Rechercher dans les métadonnées…")
        header.addWidget(self.indicators, 1)
        header.addWidget(self.search, 2)
        layout.addLayout(header)
        self.message = QLabel("Sélectionnez un fichier pour afficher ses métadonnées.", self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.model = MetadataTreeModel(self)
        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectItems)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setVisible(False)
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, 180)
        self.tree.setColumnWidth(1, 300)
        layout.addWidget(self.tree)
        self.search.textChanged.connect(self._filter)
        self.tree.customContextMenuRequested.connect(self._context_menu)

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        """Lit le cache uniquement ; l'affichage ne déclenche aucune extraction."""
        self.search.clear()
        if file_record is None:
            self._render(None)
            return
        try:
            result = (
                self._manager.cached_or_stored(file_record)
                if self._manager is not None
                else self._cache.get(file_record)
            )
            self._render(result)
        except FileIdentityError:
            self._render(None)

    def _render(self, result: MetadataResult | None) -> None:
        fields = result.fields if result and not result.unavailable_message else ()
        self.model.set_fields(fields)
        self.indicators.setText("  ".join(result.indicators) if result else "")
        self.message.setText(
            result.unavailable_message if result and result.unavailable_message else "Métadonnées indisponibles."
        )
        visible = bool(fields)
        self.message.setVisible(not visible)
        self.tree.setVisible(visible)
        if visible:
            self.tree.expandAll()

    def _filter(self, value: str) -> None:
        self.model.set_search(value)
        self.tree.expandAll()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_cell()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_cell(self) -> None:
        index = self.tree.currentIndex()
        if index.isValid():
            QApplication.clipboard().setText(str(index.data() or ""))

    def copy_line(self) -> None:
        index = self.tree.currentIndex()
        if index.isValid():
            QApplication.clipboard().setText(self.model.line_text(index))

    def copy_category(self) -> None:
        index = self.tree.currentIndex()
        if index.isValid():
            QApplication.clipboard().setText(
                self.model.category_text(index if self.model.is_category(index) else index.parent())
            )

    def _context_menu(self, point) -> None:
        menu = QMenu(self)
        menu.addAction("Copier la cellule", self.copy_cell)
        menu.addAction("Copier la ligne", self.copy_line)
        menu.addAction("Copier la catégorie", self.copy_category)
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def expanded_categories(self) -> tuple[str, ...]:
        return tuple(
            self.model.data(self.model.index(row, 0), Qt.ItemDataRole.DisplayRole)
            for row in range(self.model.rowCount())
            if self.tree.isExpanded(self.model.index(row, 0))
        )

    def restore_expanded_categories(self, labels: tuple[str, ...]) -> None:
        expanded = frozenset(labels)
        for row in range(self.model.rowCount()):
            index = self.model.index(row, 0)
            self.tree.setExpanded(index, str(self.model.data(index, Qt.ItemDataRole.DisplayRole)) in expanded)
