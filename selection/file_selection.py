"""Shared, canonical file selection independent from Qt view selection."""

from __future__ import annotations

from collections.abc import Iterable, Set
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True, slots=True)
class FileSelectionChange:
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def changed_ids(self) -> tuple[str, ...]:
        return self.added + self.removed


class FileSelectionModel(QObject):
    """Single source of truth for a project-scoped set of canonical ``file_id`` values."""

    changed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._selected: set[str] = set()

    @property
    def count(self) -> int:
        return len(self._selected)

    def contains(self, file_id: str) -> bool:
        return file_id in self._selected

    def selected_ids(self) -> Set[str]:
        """Read-only view contract over the canonical set; no O(K) copy is made."""
        return self._selected

    def select_many(self, file_ids: Iterable[str]) -> FileSelectionChange:
        added = tuple(file_id for file_id in dict.fromkeys(file_ids) if file_id and file_id not in self._selected)
        if added:
            self._selected.update(added)
        return self._publish(FileSelectionChange(added=added))

    def deselect_many(self, file_ids: Iterable[str]) -> FileSelectionChange:
        removed = tuple(file_id for file_id in dict.fromkeys(file_ids) if file_id in self._selected)
        if removed:
            self._selected.difference_update(removed)
        return self._publish(FileSelectionChange(removed=removed))

    def toggle(self, file_id: str, selected: bool) -> FileSelectionChange:
        return self.select_many((file_id,)) if selected else self.deselect_many((file_id,))

    def clear(self) -> FileSelectionChange:
        removed = tuple(self._selected)
        self._selected.clear()
        return self._publish(FileSelectionChange(removed=removed))

    def _publish(self, change: FileSelectionChange) -> FileSelectionChange:
        if change.changed_ids:
            self.changed.emit(change)
        return change
