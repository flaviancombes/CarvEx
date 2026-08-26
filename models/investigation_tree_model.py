"""Modèle Qt passif de l'arborescence Investigation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt

from investigation.target_ref import InvestigationTargetRef


class InvestigationSection(str, Enum):  # noqa: UP042 - contrat Qt existant
    ITEMS = "items"
    CASES = "cases"
    COLLECTIONS = "collections"
    POST_ITS = "post_its"
    HYPOTHESES = "hypotheses"
    NOTES = "notes"
    TAGS = "tags"
    JOURNAL = "journal"


@dataclass(frozen=True, slots=True)
class InvestigationTreeEntry:
    """Ligne UI légère : identifiant, libellé et éventuelle cible liée."""

    subject_kind: str
    subject_id: str
    title: str
    subtitle: str = ""
    related_target_ref: InvestigationTargetRef | None = None


class InvestigationTreeModel(QAbstractItemModel):
    """Arbre à deux niveaux, mis à jour section par section par le contrôleur."""

    _SECTION_LABELS = {
        InvestigationSection.ITEMS: "📄 Preuves",
        InvestigationSection.CASES: "📁 Cases",
        InvestigationSection.COLLECTIONS: "🗂 Collections",
        InvestigationSection.POST_ITS: "📝 Post-it",
        InvestigationSection.HYPOTHESES: "Hypothèses",
        InvestigationSection.NOTES: "Notes",
        InvestigationSection.TAGS: "Tags",
        InvestigationSection.JOURNAL: "Journal",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Notes et hypothèses sont des attributs d'une preuve dans l'UX ; le
        # domaine les conserve mais l'arbre ne les expose plus directement.
        self._sections = (
            InvestigationSection.ITEMS,
            InvestigationSection.CASES,
            InvestigationSection.COLLECTIONS,
            InvestigationSection.POST_ITS,
            InvestigationSection.JOURNAL,
        )
        self._entries: dict[InvestigationSection, tuple[InvestigationTreeEntry, ...]] = {
            section: () for section in self._sections
        }
        self._section_by_entry_pointer: dict[int, InvestigationSection] = {}
        self._entry_positions: dict[tuple[str, str], tuple[InvestigationSection, int]] = {}
        self._loaded: set[InvestigationSection] = set()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 1

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        if not parent.isValid():
            return len(self._sections)
        pointer = parent.internalPointer()
        if isinstance(pointer, InvestigationSection):
            return len(self._entries[pointer])
        return 0

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:  # noqa: N802, B008
        if column != 0 or row < 0:
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, self._sections[row]) if row < len(self._sections) else QModelIndex()
        section = parent.internalPointer()
        if isinstance(section, InvestigationSection):
            entries = self._entries[section]
            return self.createIndex(row, column, entries[row]) if row < len(entries) else QModelIndex()
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: N802
        if not index.isValid() or not isinstance(index.internalPointer(), InvestigationTreeEntry):
            return QModelIndex()
        entry = index.internalPointer()
        section = self._section_by_entry_pointer.get(id(entry))
        return self.createIndex(self._sections.index(section), 0, section) if section is not None else QModelIndex()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        node = index.internalPointer()
        if isinstance(node, InvestigationSection):
            return self._SECTION_LABELS[node]
        if isinstance(node, InvestigationTreeEntry):
            return node.title if not node.subtitle else f"{node.title} — {node.subtitle}"
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        entry = self.entry_for_index(index)
        if entry is None:
            return flags
        if entry.subject_kind in {"item", "collection"}:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        if entry.subject_kind in {"case", "collection"}:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802, B008
        if not parent.isValid():
            return bool(self._sections)
        return isinstance(parent.internalPointer(), InvestigationSection)

    def section_for_index(self, index: QModelIndex) -> InvestigationSection | None:
        if index.isValid() and isinstance(index.internalPointer(), InvestigationSection):
            return index.internalPointer()
        return None

    def entry_for_index(self, index: QModelIndex) -> InvestigationTreeEntry | None:
        return (
            index.internalPointer()
            if index.isValid() and isinstance(index.internalPointer(), InvestigationTreeEntry)
            else None
        )

    def index_for_entry(self, subject_kind: str, subject_id: str) -> QModelIndex:
        """Résout une entrée créée récemment sans parcourir le modèle Qt."""
        position = self._entry_positions.get((subject_kind, subject_id))
        if position is None:
            return QModelIndex()
        section, row = position
        return self.createIndex(row, 0, self._entries[section][row])

    def is_loaded(self, section: InvestigationSection) -> bool:
        return section in self._loaded

    def set_entries(self, section: InvestigationSection, entries: tuple[InvestigationTreeEntry, ...]) -> None:
        """Remplace uniquement les enfants d'une section déjà matérialisée."""
        section_row = self._sections.index(section)
        parent = self.createIndex(section_row, 0, section)
        previous = self._entries[section]
        if previous:
            self.beginRemoveRows(parent, 0, len(previous) - 1)
            self._entries[section] = ()
            for entry in previous:
                self._section_by_entry_pointer.pop(id(entry), None)
                self._entry_positions.pop((entry.subject_kind, entry.subject_id), None)
            self.endRemoveRows()
        if entries:
            self.beginInsertRows(parent, 0, len(entries) - 1)
            self._entries[section] = entries
            for row, entry in enumerate(entries):
                self._section_by_entry_pointer[id(entry)] = section
                self._entry_positions[entry.subject_kind, entry.subject_id] = section, row
            self.endInsertRows()
        self._loaded.add(section)

    def clear(self) -> None:
        """Détache un projet sans réinitialiser les nœuds de section permanents."""
        for section in self._sections:
            if self._entries[section]:
                self.set_entries(section, ())
        self._loaded.clear()
