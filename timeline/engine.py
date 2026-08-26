"""Point d'accès métier unique aux événements déjà mis en cache par fichier."""

from __future__ import annotations

from collections.abc import Mapping

from timeline.event import TimelineEvent
from timeline.manager import TimelineManager


class TimelineEngine:
    """Façade stable destinée aux vues, exports et futurs modules d'investigation."""

    def __init__(self, manager: TimelineManager) -> None:
        self._manager = manager

    def events_for(self, file_record: Mapping[str, object]) -> tuple[TimelineEvent, ...]:
        return self._manager.events_for(file_record)

    def clear_cache(self) -> None:
        """Release cached events when the repository switches report."""
        self._manager.clear_cache()
