"""Modèle Qt passif de l'onglet Bookmarks."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from bookmarks.model import Bookmark, BookmarkKey
from bookmarks.service import BookmarkService
from selection.canonical_entity_resolver import CanonicalEntityResolver


class BookmarkModel(QAbstractTableModel):
    COLUMNS = ("", "Nom du fichier", "Catégorie", "Type MIME", "Créé le", "●")
    BOOKMARK_COLUMN = 0
    INVESTIGATION_COLUMN = 5

    def __init__(
        self, service: BookmarkService, parent=None, entity_resolver: CanonicalEntityResolver | None = None
    ) -> None:
        super().__init__(parent)
        self.bookmark_service = service
        self._entity_resolver = entity_resolver or CanonicalEntityResolver()
        self._bookmarks: list[Bookmark] = list(service.all())
        self._rows = {bookmark.key: row for row, bookmark in enumerate(self._bookmarks)}
        self._records_by_key: dict[BookmarkKey, object | None] = {}
        self._investigation_lookup = None
        service.bookmarks_batch_changed.connect(self._on_batch_changed)
        service.bookmarks_reset.connect(self._reset_from_service)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._bookmarks)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        bookmark = self._bookmarks[index.row()]
        record = self._record_for(bookmark) or {}
        if index.column() == 0:
            return "★"
        if index.column() == 1:
            return str(record.get("name") or "Fichier indisponible")
        if index.column() == 2:
            return str(record.get("category") or "")
        if index.column() == 3:
            return str(record.get("mime") or "")
        if index.column() == self.INVESTIGATION_COLUMN:
            return "●" if self._investigation_lookup and self._investigation_lookup(bookmark) else ""
        return bookmark.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):  # noqa: N802
        return (
            self.COLUMNS[section]
            if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal
            else None
        )

    def bookmark_at(self, row: int) -> Bookmark | None:
        return self._bookmarks[row] if 0 <= row < len(self._bookmarks) else None

    def bookmark_key_at(self, row: int) -> BookmarkKey:
        return self._bookmarks[row].key

    def bookmark_key_for_index(self, index: QModelIndex) -> BookmarkKey:
        return self.bookmark_key_at(index.row())

    def refresh_file_projection(self) -> None:
        """Rafraîchit les libellés après le chargement du rapport actif."""
        self._records_by_key.clear()
        if self._bookmarks:
            self.dataChanged.emit(
                self.index(0, 1),
                self.index(len(self._bookmarks) - 1, self.INVESTIGATION_COLUMN),
                [Qt.ItemDataRole.DisplayRole],
            )

    def set_investigation_lookup(self, lookup) -> None:
        self._investigation_lookup = lookup
        if self._bookmarks:
            self.dataChanged.emit(
                self.index(0, self.INVESTIGATION_COLUMN),
                self.index(len(self._bookmarks) - 1, self.INVESTIGATION_COLUMN),
                [Qt.ItemDataRole.DisplayRole],
            )

    def _on_batch_changed(self, result) -> None:
        for key in result.removed_keys:
            row = self._rows.get(key)
            if row is None:
                continue
            self.beginRemoveRows(QModelIndex(), row, row)
            self._bookmarks.pop(row)
            self.endRemoveRows()
            self._reindex_rows(row)
        for key in result.added_keys:
            bookmark = self.bookmark_service.get(key)
            if bookmark is None or key in self._rows:
                continue
            row = len(self._bookmarks)
            self.beginInsertRows(QModelIndex(), row, row)
            self._bookmarks.append(bookmark)
            self._rows[key] = row
            self.endInsertRows()

    def _reindex_rows(self, start: int) -> None:
        for row in range(start, len(self._bookmarks)):
            self._rows[self._bookmarks[row].key] = row

    def _reset_from_service(self) -> None:
        self.beginResetModel()
        self._bookmarks = list(self.bookmark_service.all())
        self._rows = {bookmark.key: row for row, bookmark in enumerate(self._bookmarks)}
        self._records_by_key.clear()
        self.endResetModel()

    def _record_for(self, bookmark: Bookmark):
        if bookmark.key not in self._records_by_key:
            resolved = self._entity_resolver.resolve(bookmark)
            self._records_by_key[bookmark.key] = resolved.file_record if resolved is not None else None
        return self._records_by_key[bookmark.key]
