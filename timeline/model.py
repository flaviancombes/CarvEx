"""Projection Qt hiérarchique de la Timeline : Fichier → événements.

Les événements demeurent des objets métier plats.  Ce modèle est leur unique
projection groupée : un nœud parent représente un fichier canonique et ses
enfants représentent les ``TimelineEvent`` associés.  Aucun tri ni aucune
indentation textuelle ne simule la hiérarchie.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSortFilterProxyModel, Qt

from bookmarks.model import BookmarkKey
from bookmarks.service import BookmarkService
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.file_selection import FileSelectionChange, FileSelectionModel
from timeline.event import TimelineEvent
from timeline.filters import searchable_text
from timeline.manager import TimelineManager


@dataclass(slots=True)
class _FileNode:
    """Nœud UI léger, sans copie des événements ni du fichier source."""

    key: str
    row: int
    events: list[TimelineEvent] = field(default_factory=list)
    earliest_event: TimelineEvent | None = None


class TimelineTreeModel(QAbstractItemModel):
    """Modèle hiérarchique virtualisé : racine → fichier → événement."""

    COLUMNS = ("☐", "Date", "Heure", "Nom", "Catégorie", "Type d'événement", "Source", "Confiance", "", "●")
    SELECTION_COLUMN = 0
    BOOKMARK_COLUMN = 8
    INVESTIGATION_COLUMN = 9
    SORT_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(
        self,
        parent=None,
        bookmark_service: BookmarkService | None = None,
        entity_resolver: CanonicalEntityResolver | None = None,
        file_selection: FileSelectionModel | None = None,
    ) -> None:
        super().__init__(parent)
        self.bookmark_service = bookmark_service
        self._entity_resolver = entity_resolver or CanonicalEntityResolver()
        self._roots: list[_FileNode] = []
        self._nodes_by_key: dict[str, _FileNode] = {}
        self._events_by_id: dict[str, TimelineEvent] = {}
        self._bookmark_nodes: dict[BookmarkKey, set[str]] = {}
        self._investigation_lookup = None
        self._file_selection = file_selection or FileSelectionModel(self)
        if bookmark_service is not None:
            bookmark_service.bookmarks_changed.connect(self._on_bookmarks_changed)
            bookmark_service.bookmarks_reset.connect(self._on_bookmarks_reset)
        self._file_selection.changed.connect(self._on_file_selection_changed)

    def set_events(self, events: Sequence[TimelineEvent]) -> None:
        self.beginResetModel()
        self._roots = []
        self._nodes_by_key = {}
        self._events_by_id = {}
        self._bookmark_nodes = {}
        for event in self._new_events(events):
            self._append_to_indexes(event)
        self.endResetModel()

    def append_events(self, events: Sequence[TimelineEvent]) -> None:
        """Adds only the rows changed by one lazy-loading batch."""
        grouped: dict[str, list[TimelineEvent]] = {}
        for event in self._new_events(events):
            grouped.setdefault(self._file_key(event), []).append(event)

        new_groups: list[tuple[str, list[TimelineEvent]]] = []
        existing_groups: list[tuple[_FileNode, list[TimelineEvent]]] = []
        for key, group in grouped.items():
            node = self._nodes_by_key.get(key)
            if node is None:
                new_groups.append((key, group))
            else:
                existing_groups.append((node, group))

        if new_groups:
            first_row = len(self._roots)
            self.beginInsertRows(QModelIndex(), first_row, first_row + len(new_groups) - 1)
            for key, group in new_groups:
                node = _FileNode(key, len(self._roots))
                self._roots.append(node)
                self._nodes_by_key[key] = node
                self._append_group_to_node(node, group)
            self.endInsertRows()

        for node, group in existing_groups:
            parent = self._index_for_node(node, 0)
            row = len(node.events)
            self.beginInsertRows(parent, row, row + len(group) - 1)
            self._append_group_to_node(node, group)
            self.endInsertRows()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        if not parent.isValid():
            return len(self._roots)
        pointer = parent.internalPointer()
        return len(pointer.events) if isinstance(pointer, _FileNode) else 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return len(self.COLUMNS)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: N802, B008
        if row < 0 or column < 0 or column >= len(self.COLUMNS):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, self._roots[row]) if row < len(self._roots) else QModelIndex()
        node = parent.internalPointer()
        if not isinstance(node, _FileNode) or row >= len(node.events):
            return QModelIndex()
        return self.createIndex(row, column, node.events[row])

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: N802
        if not index.isValid():
            return QModelIndex()
        pointer = index.internalPointer()
        if isinstance(pointer, _FileNode):
            return QModelIndex()
        if isinstance(pointer, TimelineEvent):
            node = self._nodes_by_key.get(self._file_key(pointer))
            return self._index_for_node(node, 0) if node is not None else QModelIndex()
        return QModelIndex()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        pointer = index.internalPointer()
        if isinstance(pointer, _FileNode):
            return self._file_data(pointer, index.column(), role)
        if isinstance(pointer, TimelineEvent):
            return self._event_data(pointer, index.column(), role)
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if section == self.SELECTION_COLUMN:
                return "☑" if self._file_selection.count else "☐"
            return self.COLUMNS[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == self.SELECTION_COLUMN and self.is_file_index(index):
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if (
            not index.isValid()
            or index.column() != self.SELECTION_COLUMN
            or not self.is_file_index(index)
            or role != Qt.ItemDataRole.CheckStateRole
        ):
            return False
        node = index.internalPointer()
        if not isinstance(node, _FileNode):
            return False
        self._file_selection.toggle(node.key, value == Qt.CheckState.Checked)
        return True

    def event_for_index(self, index: QModelIndex) -> TimelineEvent | None:
        """Retourne l'événement enfant, ou le premier événement d'un fichier parent."""
        if not index.isValid():
            return None
        pointer = index.internalPointer()
        if isinstance(pointer, TimelineEvent):
            return pointer
        return pointer.events[0] if isinstance(pointer, _FileNode) and pointer.events else None

    @staticmethod
    def is_file_index(index: QModelIndex) -> bool:
        return index.isValid() and isinstance(index.internalPointer(), _FileNode)

    def file_id_for_index(self, index: QModelIndex) -> str | None:
        """Return the canonical identifier carried by a file parent node."""
        pointer = index.internalPointer() if index.isValid() else None
        return pointer.key if isinstance(pointer, _FileNode) else None

    def record_for_file_id(self, file_id: str):
        """Return the referenced report record without duplicating it."""
        node = self._nodes_by_key.get(file_id)
        return node.events[0].file_record if node is not None and node.events else None

    def event_at(self, row: int) -> TimelineEvent | None:
        """Compatibilité lecture seule : premier événement du nœud racine demandé."""
        return self.event_for_index(self.index(row, 0))

    def event_for_id(self, event_id: str) -> TimelineEvent | None:
        return self._events_by_id.get(event_id)

    def bookmark_key_at(self, index_or_row: QModelIndex | int) -> BookmarkKey | None:
        if isinstance(index_or_row, int):
            event = self.event_at(index_or_row)
        else:
            event = self.event_for_index(index_or_row)
        return self.bookmark_key_at_event(event) if event is not None else None

    def bookmark_key_for_index(self, index: QModelIndex) -> BookmarkKey | None:
        return self.bookmark_key_at(index)

    def bookmark_key_at_event(self, event: TimelineEvent) -> BookmarkKey | None:
        return self._entity_resolver.bookmark_key_for(event)

    def set_investigation_lookup(self, lookup) -> None:
        if lookup == self._investigation_lookup:
            return
        self._investigation_lookup = lookup
        self._emit_column_changed(self.INVESTIGATION_COLUMN)

    def refresh_investigation_markers(self, file_ids: Iterable[str]) -> None:
        """Notifie les seuls nœuds dont l'indicateur Investigation a changé."""
        for file_id in dict.fromkeys(file_id for file_id in file_ids if file_id):
            node = self._nodes_by_key.get(file_id)
            if node is not None:
                self._emit_node_column_changed(node, self.INVESTIGATION_COLUMN)

    def _append_to_indexes(self, event: TimelineEvent, node: _FileNode | None = None) -> None:
        node = node or self._nodes_by_key.get(self._file_key(event))
        if node is None:
            node = _FileNode(self._file_key(event), len(self._roots))
            self._roots.append(node)
            self._nodes_by_key[node.key] = node
        self._append_group_to_node(node, (event,))

    def _append_group_to_node(self, node: _FileNode, events: Sequence[TimelineEvent]) -> None:
        """Updates Python indexes once per batch, without Qt work per event."""
        for event in events:
            node.events.append(event)
            if node.earliest_event is None or TimelineManager._sort_key(event) < TimelineManager._sort_key(
                node.earliest_event
            ):
                node.earliest_event = event
            if event.event_id:
                self._events_by_id[event.event_id] = event
            key = self.bookmark_key_at_event(event)
            if key is not None:
                self._bookmark_nodes.setdefault(key, set()).add(node.key)

    def _new_events(self, events: Sequence[TimelineEvent]) -> tuple[TimelineEvent, ...]:
        """Keep an event insertion idempotent across lazy batches and reloads."""
        unique: list[TimelineEvent] = []
        seen_in_batch: set[str] = set()
        for event in events:
            event_id = event.event_id
            if event_id and (event_id in self._events_by_id or event_id in seen_in_batch):
                continue
            unique.append(event)
            if event_id:
                seen_in_batch.add(event_id)
        return tuple(unique)

    def _file_key(self, event: TimelineEvent) -> str:
        return self._entity_resolver.file_id_for(event) or event.event_id

    def _index_for_node(self, node: _FileNode, column: int) -> QModelIndex:
        return self.createIndex(node.row, column, node)

    def _file_data(self, node: _FileNode, column: int, role: int):
        event = node.events[0] if node.events else None
        if event is None:
            return None
        record = event.file_record or {}
        if column == self.SELECTION_COLUMN:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if self._file_selection.contains(node.key) else Qt.CheckState.Unchecked
            return None
        if role == Qt.ItemDataRole.UserRole:
            return event
        if role == self.SORT_ROLE:
            return self._file_sort_value(node, column)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if column == self.BOOKMARK_COLUMN:
            key = self.bookmark_key_at_event(event)
            return "★" if key is not None and self.bookmark_service and self.bookmark_service.contains(key) else "☆"
        if column == self.INVESTIGATION_COLUMN:
            return "●" if self._is_in_investigation(event) else ""
        if column == 1:
            return node.earliest_event.date.strftime("%Y-%m-%d") if node.earliest_event is not None else ""
        if column == 2:
            return ""
        if column == 3:
            return f"📄 {record.get('name') or 'Sans nom'}"
        if column == 4:
            return str(record.get("category") or "Inconnu")
        if column == 5:
            return f"{len(node.events)} événement(s)"
        return ""

    def _event_data(self, event: TimelineEvent, column: int, role: int):
        record = event.file_record or {}
        if column == self.SELECTION_COLUMN:
            return None
        if role == Qt.ItemDataRole.UserRole:
            return event
        if role == self.SORT_ROLE:
            return self._event_sort_value(event, column)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if column == self.BOOKMARK_COLUMN:
            key = self.bookmark_key_at_event(event)
            return "★" if key is not None and self.bookmark_service and self.bookmark_service.contains(key) else "☆"
        if column == self.INVESTIGATION_COLUMN:
            return "●" if self._is_in_investigation(event) else ""
        if column == 1:
            return event.date.strftime("%Y-%m-%d")
        if column == 2:
            return event.date.strftime("%H:%M:%S %z").rstrip() if event.date.tzinfo else event.date.strftime("%H:%M:%S")
        if column == 3:
            return ""
        if column == 4:
            return str(record.get("category") or "Inconnu")
        if column == 5:
            return f"{event.event_type.icon} {event.event_type.label}"
        if column == 6:
            return event.source.label
        return event.confidence.value

    def _file_sort_value(self, node: _FileNode, column: int) -> str:
        event = node.events[0]
        record = event.file_record or {}
        values = {
            self.SELECTION_COLUMN: "1" if self._file_selection.contains(node.key) else "0",
            self.BOOKMARK_COLUMN: "1" if self._bookmark_key_is_present(event) else "0",
            1: TimelineManager._sort_key(node.earliest_event).isoformat() if node.earliest_event is not None else "",
            3: str(record.get("name") or "").casefold(),
            4: str(record.get("category") or "").casefold(),
            5: f"{len(node.events):010d}",
            self.INVESTIGATION_COLUMN: "1" if self._is_in_investigation(event) else "0",
        }
        return values.get(column, self._file_key(event))

    def _event_sort_value(self, event: TimelineEvent, column: int) -> str:
        record = event.file_record or {}
        values = {
            self.BOOKMARK_COLUMN: "1" if self._bookmark_key_is_present(event) else "0",
            1: event.date.isoformat(),
            2: event.date.isoformat(),
            4: str(record.get("category") or "").casefold(),
            5: event.event_type.label.casefold(),
            6: event.source.label.casefold(),
            7: event.confidence.value,
            TimelineTreeModel.INVESTIGATION_COLUMN: "1" if self._is_in_investigation(event) else "0",
        }
        return values.get(column, event.event_id)

    def _bookmark_key_is_present(self, event: TimelineEvent) -> bool:
        key = self.bookmark_key_at_event(event)
        return bool(key is not None and self.bookmark_service and self.bookmark_service.contains(key))

    def _is_in_investigation(self, event: TimelineEvent) -> bool:
        """Une vue fermée ne doit jamais relancer un service Investigation inactif."""
        if self._investigation_lookup is None:
            return False
        try:
            return bool(self._investigation_lookup(event))
        except RuntimeError:
            return False

    def _on_bookmarks_changed(self, keys: tuple[BookmarkKey, ...]) -> None:
        for key in keys:
            for node_key in self._bookmark_nodes.get(key, ()):
                node = self._nodes_by_key.get(node_key)
                if node is not None:
                    self._emit_node_column_changed(node, self.BOOKMARK_COLUMN)

    def _on_bookmarks_reset(self) -> None:
        self._emit_column_changed(self.BOOKMARK_COLUMN)

    def _on_file_selection_changed(self, change: FileSelectionChange) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, self.SELECTION_COLUMN, self.SELECTION_COLUMN)
        for file_id in change.changed_ids:
            node = self._nodes_by_key.get(file_id)
            if node is None:
                continue
            index = self._index_for_node(node, self.SELECTION_COLUMN)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole, self.SORT_ROLE])

    def _emit_node_column_changed(self, node: _FileNode, column: int) -> None:
        group = self._index_for_node(node, column)
        self.dataChanged.emit(group, group, [Qt.ItemDataRole.DisplayRole])
        if node.events:
            parent = self._index_for_node(node, 0)
            first = self.index(0, column, parent)
            last = self.index(len(node.events) - 1, column, parent)
            self.dataChanged.emit(first, last, [Qt.ItemDataRole.DisplayRole])

    def _emit_column_changed(self, column: int) -> None:
        for node in self._roots:
            self._emit_node_column_changed(node, column)


# Nom historique conservé pour les extensions existantes ; le modèle n'est plus plat.
TimelineTableModel = TimelineTreeModel


class TimelineFilterProxyModel(QSortFilterProxyModel):
    """Filtre hiérarchique : un fichier est visible si l'un de ses événements correspond."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._search = ""
        self._category = ""
        self._event_type = ""
        self._search_texts: dict[int, str] = {}
        self._building = False
        self.setDynamicSortFilter(True)
        self.setRecursiveFilteringEnabled(True)
        self.setSortRole(TimelineTreeModel.SORT_ROLE)

    def set_filters(self, search: str, category: str, event_type: str) -> None:
        values = (search.casefold().strip(), category, event_type)
        if values == (self._search, self._category, self._event_type):
            return
        if not self._building:
            self.beginFilterChange()
        self._search, self._category, self._event_type = values
        if not self._search:
            self._search_texts.clear()
        if not self._building:
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_building(self, building: bool) -> None:
        """Defer one expensive hierarchical filter pass until background construction ends."""
        if building == self._building:
            return
        self._building = building
        if not building:
            self.beginFilterChange()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def setSourceModel(self, source_model) -> None:  # noqa: N802
        previous = self.sourceModel()
        if previous is not None:
            previous.modelReset.disconnect(self._search_texts.clear)
        super().setSourceModel(source_model)
        if source_model is not None:
            source_model.modelReset.connect(self._search_texts.clear)

    def set_grouping(self, _grouping: str) -> None:
        """Compatibilité workspace : la hiérarchie est désormais toujours par fichier."""

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, TimelineTreeModel):
            return False
        if self._building:
            return True
        index = model.index(source_row, 0, source_parent)
        event = model.event_for_index(index)
        if event is None:
            return False
        record = event.file_record or {}
        if self._category and str(record.get("category") or "") != self._category:
            return False
        if self._event_type and event.event_type.identifier != self._event_type:
            return False
        if not self._search:
            return True
        event_identity = id(event)
        text = self._search_texts.get(event_identity)
        if text is None:
            text = searchable_text(event)
            self._search_texts[event_identity] = text
        return self._search in text

    def event_for_index(self, index: QModelIndex) -> TimelineEvent | None:
        if not index.isValid():
            return None
        source = self.mapToSource(index)
        model = self.sourceModel()
        return model.event_for_index(source) if isinstance(model, TimelineTreeModel) else None

    def is_file_index(self, index: QModelIndex) -> bool:
        if not index.isValid():
            return False
        source = self.mapToSource(index)
        model = self.sourceModel()
        return isinstance(model, TimelineTreeModel) and model.is_file_index(source)
