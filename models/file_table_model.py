"""Modèle Qt en lecture seule pour les fichiers d'un rapport CarvEx."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class FileTableModel(QAbstractTableModel):
    """Expose les enregistrements backend sans les recopier ni les recalculer."""

    COLUMNS = (
        ("Nom", "name"),
        ("Catégorie", "category"),
        ("Type MIME", "mime"),
        ("Taille", "size"),
        ("SHA-256", "sha256"),
    )

    def __init__(self, records: Sequence[Mapping[str, Any]] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._records: Sequence[Mapping[str, Any]] = records if records is not None else ()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        _, field = self.COLUMNS[index.column()]
        value = self._records[index.row()].get(field, "")
        return "" if value is None else str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][0]
        return None

    def set_records(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.beginResetModel()
        self._records = records
        self.endResetModel()

    def record_at(self, row: int) -> Mapping[str, Any] | None:
        """Retourne l'enregistrement backend complet de la ligne demandée."""
        if 0 <= row < len(self._records):
            return self._records[row]
        return None
