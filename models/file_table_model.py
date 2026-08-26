"""Modèle Qt en lecture seule pour les fichiers d'un rapport CarvEx."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from bookmarks.model import BookmarkKey
from bookmarks.service import BookmarkService
from core.duplicates import DuplicateIndex
from metadata.correlation import MetadataCorrelationIndex
from metadata.index import MetadataIndex
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.file_selection import FileSelectionChange, FileSelectionModel
from utils.performance import format_byte_size


@dataclass(frozen=True, slots=True)
class _FilterRow:
    """Valeurs immuables nécessaires aux filtres, préparées une fois par corpus."""

    category: object
    is_image: bool
    search_fields: tuple[str, ...]
    numeric_size: int | None
    file_id: str | None


class FileTableModel(QAbstractTableModel):
    """Expose les enregistrements backend sans les recopier ni les recalculer."""

    COLUMNS = (
        ("☐", "selection"),
        ("", "bookmark"),
        ("Investigation", "investigation"),
        ("Nom", "name"),
        ("Catégorie", "category"),
        ("Type MIME", "mime"),
        ("Taille", "size"),
        ("Nombre de copies", "duplicate_count"),
        ("SHA-256", "sha256"),
        ("Corrélations", "correlations"),
    )

    SELECTION_COLUMN = 0
    BOOKMARK_COLUMN = 1
    INVESTIGATION_COLUMN = 2
    SIZE_COLUMN = 6
    DUPLICATE_COUNT_COLUMN = 7
    SHA256_COLUMN = 8
    CORRELATIONS_COLUMN = 9
    SEARCH_FIELDS = ("name", "category", "mime", "sha256", "output", "source_path")

    def __init__(
        self,
        records: Sequence[Mapping[str, Any]] | None = None,
        parent=None,
        bookmark_service: BookmarkService | None = None,
        investigation_file_lookup: Callable[[str], bool] | None = None,
        entity_resolver: CanonicalEntityResolver | None = None,
        file_selection: FileSelectionModel | None = None,
        duplicate_index: DuplicateIndex | None = None,
    ) -> None:
        super().__init__(parent)
        self._records: Sequence[Mapping[str, Any]] = ()
        self.bookmark_service = bookmark_service
        self._entity_resolver = entity_resolver or CanonicalEntityResolver()
        self._investigation_file_lookup = investigation_file_lookup
        self._file_selection = file_selection or FileSelectionModel(self)
        self._duplicate_index = duplicate_index or DuplicateIndex()
        self._correlation_index: MetadataCorrelationIndex | None = None
        self._metadata_index: MetadataIndex | None = None
        self._correlation_counts: dict[str, int] = {}
        self._bookmark_rows: dict[str, list[int]] = {}
        self._filter_rows: list[_FilterRow] = []
        if bookmark_service is not None:
            bookmark_service.bookmarks_changed.connect(self._on_bookmarks_changed)
            bookmark_service.bookmarks_reset.connect(self._on_bookmarks_reset)
        self._file_selection.changed.connect(self._on_selection_changed)
        if records is not None:
            self._set_records_data(records)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        _, field = self.COLUMNS[index.column()]
        if field == "selection":
            if role == Qt.ItemDataRole.CheckStateRole:
                file_id = self._entity_resolver.file_id_for(self._records[index.row()])
                return (
                    Qt.CheckState.Checked
                    if file_id is not None and self._file_selection.contains(file_id)
                    else Qt.CheckState.Unchecked
                )
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip_at(index.row())
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if field == "bookmark":
            key = self.bookmark_key_at(index.row())
            return "★" if key is not None and self.bookmark_service and self.bookmark_service.contains(key) else "☆"
        if field == "investigation":
            file_id = self._entity_resolver.file_id_for(self._records[index.row()])
            return (
                "●"
                if file_id is not None and self._investigation_file_lookup and self._investigation_file_lookup(file_id)
                else ""
            )
        if field == "duplicate_count":
            return self.duplicate_count_at(index.row())
        if field == "correlations":
            file_id = self.file_id_at(index.row())
            return self._correlation_counts.get(file_id or "", 0)
        value = self._records[index.row()].get(field, "")
        if field == "size":
            return format_byte_size(value)
        return "" if value is None else str(value)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section == self.SELECTION_COLUMN:
                return "☑" if self._file_selection.count else "☐"
            return self.COLUMNS[section][0]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.column() == self.SELECTION_COLUMN else flags

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or index.column() != self.SELECTION_COLUMN or role != Qt.ItemDataRole.CheckStateRole:
            return False
        file_id = self._entity_resolver.file_id_for(self._records[index.row()])
        if file_id is None:
            return False
        self._file_selection.toggle(file_id, value == Qt.CheckState.Checked)
        return True

    def set_records(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.beginResetModel()
        self._set_records_data(records)
        self.endResetModel()

    def filter_row_at(self, row: int) -> _FilterRow | None:
        if 0 <= row < len(self._filter_rows):
            return self._filter_rows[row]
        return None

    def numeric_size_at(self, row: int) -> int | None:
        filter_row = self.filter_row_at(row)
        return filter_row.numeric_size if filter_row is not None else None

    def duplicate_count_at(self, row: int) -> int:
        file_id = self.file_id_at(row)
        return self._duplicate_index.copy_count(file_id) if file_id is not None else 1

    def correlation_count_at(self, row: int) -> int:
        file_id = self.file_id_at(row)
        return self._correlation_counts.get(file_id or "", 0)

    def correlation_count_for_file(self, file_id: str) -> int:
        return self._correlation_counts.get(file_id, 0)

    def set_correlation_index(self, index: MetadataCorrelationIndex | None) -> None:
        """Prépare une fois les compteurs de la colonne depuis l'index persistant."""
        self._correlation_index = index
        counts: dict[str, int] = {}
        if index is not None:
            for correlation in index.all():
                for file_id in correlation.file_ids:
                    counts[file_id] = counts.get(file_id, 0) + 1
        self._correlation_counts = counts
        if self._records:
            self.dataChanged.emit(
                self.index(0, self.CORRELATIONS_COLUMN),
                self.index(len(self._records) - 1, self.CORRELATIONS_COLUMN),
                [Qt.ItemDataRole.DisplayRole],
            )

    def set_metadata_index(self, index: MetadataIndex | None) -> None:
        self._metadata_index = index

    def _set_records_data(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records = records
        self._bookmark_rows = {}
        self._filter_rows = []
        for row, record in enumerate(records):
            file_id = self._entity_resolver.file_id_for(record)
            if file_id is not None:
                self._bookmark_rows.setdefault(file_id, []).append(row)
            mime = str(record.get("mime") or "").lower()
            self._filter_rows.append(
                _FilterRow(
                    category=record.get("category"),
                    is_image=record.get("category") == "Images" or mime.startswith("image/"),
                    search_fields=tuple(
                        self._normalized_search_value(record.get(field, "")) for field in self.SEARCH_FIELDS
                    ),
                    numeric_size=self._numeric_size(record.get("size")),
                    file_id=file_id,
                )
            )

    @staticmethod
    def _numeric_size(value: object) -> int | None:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalized_search_value(value: object) -> str:
        text = str(value)
        normalized = text.casefold()
        return text if normalized == text else normalized

    def set_investigation_file_lookup(self, lookup: Callable[[str], bool] | None) -> None:
        self._investigation_file_lookup = lookup
        self.refresh_investigation_marker()

    def refresh_investigation_marker(self, file_id: str | None = None) -> None:
        """Met à jour uniquement les cellules d'icône concernées, sans reset du modèle."""
        rows = self._bookmark_rows.get(file_id, ()) if file_id else range(len(self._records))
        for row in rows:
            index = self.index(row, self.INVESTIGATION_COLUMN)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

    def refresh_investigation_markers(self, file_ids: Sequence[str]) -> None:
        rows = sorted({row for file_id in dict.fromkeys(file_ids) for row in self._bookmark_rows.get(file_id, ())})
        if not rows:
            return
        if len(rows) > 128:
            self.dataChanged.emit(
                self.index(rows[0], self.INVESTIGATION_COLUMN),
                self.index(rows[-1], self.INVESTIGATION_COLUMN),
                [Qt.ItemDataRole.DisplayRole],
            )
            return
        start = previous = rows[0]
        for row in (*rows[1:], None):
            if row is not None and row == previous + 1:
                previous = row
                continue
            self.dataChanged.emit(
                self.index(start, self.INVESTIGATION_COLUMN),
                self.index(previous, self.INVESTIGATION_COLUMN),
                [Qt.ItemDataRole.DisplayRole],
            )
            if row is not None:
                start = previous = row

    def refresh_artifact_rows(self, file_ids: Sequence[str]) -> None:
        """Notifie le proxy des seuls fichiers dont le cache d'artefacts a changÃ©."""
        for file_id in dict.fromkeys(file_ids):
            for row in self._bookmark_rows.get(file_id, ()):
                self.dataChanged.emit(
                    self.index(row, 0),
                    self.index(row, len(self.COLUMNS) - 1),
                    [Qt.ItemDataRole.DisplayRole],
                )

    def record_at(self, row: int) -> Mapping[str, Any] | None:
        """Retourne l'enregistrement backend complet de la ligne demandée."""
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def bookmark_key_at(self, row: int) -> BookmarkKey | None:
        return self._entity_resolver.bookmark_key_for(self._records[row])

    def file_id_at(self, row: int) -> str | None:
        return self._entity_resolver.file_id_for(self._records[row]) if 0 <= row < len(self._records) else None

    def file_ids(self) -> tuple[str, ...]:
        """Canonical ids exposed once for index-only filters."""
        return tuple(row.file_id for row in self._filter_rows if row.file_id is not None)

    def file_label_for(self, file_id: str) -> str:
        rows = self._bookmark_rows.get(file_id, ())
        if rows:
            return str(self._records[rows[0]].get("name") or file_id)
        return file_id

    def row_for_file(self, file_id: str) -> int | None:
        rows = self._bookmark_rows.get(file_id, ())
        return rows[0] if rows else None

    def _tooltip_at(self, row: int) -> str:
        record = self.record_at(row)
        if record is None:
            return ""
        file_id = self.file_id_at(row) or ""
        lines = [
            str(record.get("name") or "Sans nom"),
            f"Taille : {format_byte_size(record.get('size'))}",
            f"Type : {record.get('mime') or record.get('category') or 'inconnu'}",
        ]
        sha256 = str(record.get("sha256") or "")
        if sha256:
            lines.append(f"SHA-256 : {sha256[:16]}…")
        if self._metadata_index is not None and file_id:
            camera = self._metadata_index.values_for("exif.model").get(file_id)
            gps = self._metadata_index.values_for("exif.gps.latitude").get(file_id)
            if camera:
                lines.append(f"Appareil : {camera}")
            if gps is not None:
                lines.append("GPS : présent")
        lines.append(f"Corrélations : {self._correlation_counts.get(file_id, 0)}")
        lines.append(f"Doublons : {self._duplicate_index.copy_count(file_id) if file_id else 1}")
        return "\n".join(lines)

    def _on_selection_changed(self, change: FileSelectionChange) -> None:
        rows = sorted({row for file_id in change.changed_ids for row in self._bookmark_rows.get(file_id, ())})
        if not rows:
            return
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, self.SELECTION_COLUMN, self.SELECTION_COLUMN)
        if len(rows) > 128:
            self.dataChanged.emit(
                self.index(rows[0], self.SELECTION_COLUMN),
                self.index(rows[-1], self.SELECTION_COLUMN),
                [Qt.ItemDataRole.CheckStateRole],
            )
            return
        start = previous = rows[0]
        for row in (*rows[1:], None):
            if row is not None and row == previous + 1:
                previous = row
                continue
            self.dataChanged.emit(
                self.index(start, self.SELECTION_COLUMN),
                self.index(previous, self.SELECTION_COLUMN),
                [Qt.ItemDataRole.CheckStateRole],
            )
            if row is not None:
                start = previous = row

    def bookmark_key_for_index(self, index: QModelIndex) -> BookmarkKey | None:
        return self.bookmark_key_at(index.row())

    def _on_bookmarks_changed(self, keys: tuple[BookmarkKey, ...]) -> None:
        for key in keys:
            if key.subject_kind != "file":
                continue
            for row in self._bookmark_rows.get(key.subject_id, ()):
                index = self.index(row, self.BOOKMARK_COLUMN)
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

    def _on_bookmarks_reset(self) -> None:
        if self._records:
            self.dataChanged.emit(
                self.index(0, self.BOOKMARK_COLUMN),
                self.index(len(self._records) - 1, self.BOOKMARK_COLUMN),
                [Qt.ItemDataRole.DisplayRole],
            )
