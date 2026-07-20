"""Proxy Qt combinant recherche textuelle, catégories et tri natif."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel

from models.file_table_model import FileTableModel


class FileFilterProxyModel(QSortFilterProxyModel):
    """Filtre les enregistrements du modèle source sans créer de liste dérivée."""

    SEARCH_FIELDS = ("name", "category", "mime", "sha256", "output", "source_path")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._search_text = ""
        self._category = ""
        self.setDynamicSortFilter(True)
        self.setSortLocaleAware(True)

    def set_search_text(self, text: str) -> None:
        self._search_text = text.casefold().strip()
        self.invalidateFilter()

    def set_category(self, category: str) -> None:
        self._category = category
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        record = self._record_for_row(source_row)
        if record is None:
            return False
        if self._category and record.get("category") != self._category:
            return False
        if not self._search_text:
            return True
        return any(
            self._search_text in str(record.get(field, "")).casefold()
            for field in self.SEARCH_FIELDS
        )

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        if left.column() == 3:
            try:
                return int(left.data() or 0) < int(right.data() or 0)
            except (TypeError, ValueError):
                pass
        return super().lessThan(left, right)

    def _record_for_row(self, row: int) -> Mapping[str, object] | None:
        model = self.sourceModel()
        if isinstance(model, FileTableModel):
            return model.record_at(row)
        return None
