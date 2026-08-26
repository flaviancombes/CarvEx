"""Cache mémoire des événements, indexé comme les métadonnées CarvEx."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock

from core.file_identity import require_file_id
from timeline.event import TimelineEvent


class TimelineCache:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[TimelineEvent, ...]] = {}
        self._lock = RLock()

    def get(self, file_record: Mapping[str, object]) -> tuple[TimelineEvent, ...] | None:
        with self._lock:
            return self._entries.get(require_file_id(file_record))

    def set(self, file_record: Mapping[str, object], events: tuple[TimelineEvent, ...]) -> None:
        with self._lock:
            self._entries[require_file_id(file_record)] = events

    def clear(self) -> None:
        """Release cached events when the active report is replaced."""
        with self._lock:
            self._entries.clear()
