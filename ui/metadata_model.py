"""Modèle hiérarchique virtualisé des champs de métadonnées."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt

from metadata.base import MetadataCategory, MetadataField
from utils.performance import format_byte_size


class _Group:
    def __init__(self, category: MetadataCategory, fields: tuple[MetadataField, ...]) -> None:
        self.category = category
        self.fields = fields


class MetadataTreeModel(QAbstractItemModel):
    """Expose seulement les champs visibles ; aucune extraction n'est déclenchée."""

    HEADERS = ("Nom", "Valeur", "Source")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all_groups: tuple[_Group, ...] = ()
        self._groups: tuple[_Group, ...] = ()
        self._search = ""

    def set_fields(self, fields: tuple[MetadataField, ...]) -> None:
        grouped: dict[MetadataCategory, list[MetadataField]] = {}
        for field in fields:
            grouped.setdefault(field.category, []).append(field)
        self._all_groups = tuple(
            _Group(category, tuple(sorted(items, key=lambda item: item.sort_key)))
            for category, items in sorted(grouped.items(), key=lambda item: list(MetadataCategory).index(item[0]))
        )
        self._apply_filter()

    def set_search(self, value: str) -> None:
        normalized = value.casefold().strip()
        if normalized == self._search:
            return
        self._search = normalized
        self._apply_filter()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        parent = parent or QModelIndex()
        if not parent.isValid():
            return len(self._groups)
        node = self._node(parent)
        if node is None or self._is_child(parent):
            return 0
        return len(self._groups[parent.row()].fields)

    def columnCount(self, _parent: QModelIndex | None = None) -> int:  # noqa: N802
        return len(self.HEADERS)

    def index(self, row: int, column: int, parent: QModelIndex | None = None) -> QModelIndex:  # noqa: N802
        parent = parent or QModelIndex()
        if row < 0 or column < 0 or column >= len(self.HEADERS):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, row + 1) if row < len(self._groups) else QModelIndex()
        if self._is_child(parent) or parent.row() >= len(self._groups) or row >= len(self._groups[parent.row()].fields):
            return QModelIndex()
        return self.createIndex(row, column, self._child_id(parent.row(), row))

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid() or not self._is_child(index):
            return QModelIndex()
        group = self._group_for_child(index)
        return self.createIndex(group, 0, group + 1)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        if not self._is_child(index):
            return self._groups[index.row()].category.value.title() if index.column() == 0 else ""
        field = self._groups[self._group_for_child(index)].fields[index.row()]
        values = (field.display_name, self._display_value(field), field.source)
        return values[index.column()]

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index: QModelIndex):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if index.isValid() else Qt.ItemFlag.NoItemFlags

    def is_category(self, index: QModelIndex) -> bool:
        return index.isValid() and not self._is_child(index)

    def category_text(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        group = index.row() if not self._is_child(index) else self._group_for_child(index)
        return "\n".join(
            "\t".join((field.display_name, self._display_value(field), field.source))
            for field in self._groups[group].fields
        )

    def line_text(self, index: QModelIndex) -> str:
        if not index.isValid() or not self._is_child(index):
            return self.category_text(index)
        field = self._groups[self._group_for_child(index)].fields[index.row()]
        return "\t".join((field.display_name, self._display_value(field), field.source))

    @staticmethod
    def _display_value(field: MetadataField) -> str:
        if field.identifier.endswith(("_size", ".size")) and isinstance(field.value, int):
            return format_byte_size(field.value)
        if "date" in field.identifier or field.identifier.endswith((".created", ".modified")):
            try:
                value = str(field.value).replace("Z", "+00:00")
                return datetime.fromisoformat(value).isoformat()
            except ValueError:
                for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(str(field.value), pattern).isoformat()
                    except ValueError:
                        continue
        return field.display_value

    def _apply_filter(self) -> None:
        self.beginResetModel()
        if not self._search:
            self._groups = self._all_groups
        else:
            self._groups = tuple(
                _Group(
                    group.category,
                    tuple(
                        field
                        for field in group.fields
                        if self._search in field.display_name.casefold()
                        or self._search in field.display_value.casefold()
                        or self._search in field.source.casefold()
                    ),
                )
                for group in self._all_groups
                if any(
                    self._search in field.display_name.casefold()
                    or self._search in field.display_value.casefold()
                    or self._search in field.source.casefold()
                    for field in group.fields
                )
            )
        self.endResetModel()

    @staticmethod
    def _child_id(group: int, row: int) -> int:
        return (1 << 31) | (group << 16) | row

    @staticmethod
    def _is_child(index: QModelIndex) -> bool:
        return bool(index.internalId() & (1 << 31))

    @staticmethod
    def _group_for_child(index: QModelIndex) -> int:
        return (index.internalId() >> 16) & 0x7FFF

    def _node(self, index: QModelIndex) -> _Group | None:
        if not index.isValid() or self._is_child(index) or index.row() >= len(self._groups):
            return None
        return self._groups[index.row()]
