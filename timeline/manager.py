"""Orchestration, tri, détection d'anomalies et cache de chronologie."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime

from core.file_identity import require_file_id
from metadata.manager import MetadataManager
from timeline.cache import TimelineCache
from timeline.event import TimelineEvent
from timeline.extractor import FilesystemTimelineExtractor, ImageExifTimelineExtractor, TimelineExtractor

LOGGER = logging.getLogger(__name__)


class TimelineManager:
    def __init__(self, extractors: Iterable[TimelineExtractor], cache: TimelineCache | None = None) -> None:
        self._extractors = tuple(extractors)
        self._cache = cache or TimelineCache()

    def events_for(self, file_record: Mapping[str, object]) -> tuple[TimelineEvent, ...]:
        cached = self._cache.get(file_record)
        if cached is not None:
            return cached
        events: list[TimelineEvent] = []
        for extractor in self._extractors:
            try:
                events.extend(extractor.extract(file_record))
            except Exception:
                LOGGER.exception("Extraction temporelle impossible pour %s", file_record.get("name"))
        result = self._mark_anomalies(tuple(sorted(self._attach_file(file_record, events), key=self._sort_key)))
        self._cache.set(file_record, result)
        return result

    def clear_cache(self) -> None:
        """Detach all events associated with the previous report."""
        self._cache.clear()

    @staticmethod
    def _attach_file(file_record: Mapping[str, object], events: Iterable[TimelineEvent]) -> Iterable[TimelineEvent]:
        """Attache la même référence de fichier, sans copier les données du rapport."""
        file_key = require_file_id(file_record)
        for index, event in enumerate(events):
            yield replace(event, event_id=f"{file_key}:{event.event_type.identifier}:{index}", file_record=file_record)

    @staticmethod
    def _sort_key(event: TimelineEvent) -> datetime:
        return event.date if event.date.tzinfo else event.date.replace(tzinfo=UTC)

    def _mark_anomalies(self, events: tuple[TimelineEvent, ...]) -> tuple[TimelineEvent, ...]:
        current_time = datetime.now(UTC)
        local_current_time = datetime.now()
        marked: list[TimelineEvent] = []
        modified_dates = [
            self._sort_key(event) for event in events if event.event_type.identifier == "filesystem.modified"
        ]
        created_dates = [
            self._sort_key(event) for event in events if event.event_type.identifier == "filesystem.created"
        ]
        for event in events:
            date = self._sort_key(event)
            comments: list[str] = []
            if (event.date.tzinfo and date > current_time) or (
                event.date.tzinfo is None and event.date > local_current_time
            ):
                comments.append("Date située dans le futur.")
            if event.event_type.identifier.startswith("exif.") and modified_dates and date > min(modified_dates):
                comments.append("Date EXIF postérieure à la modification du fichier.")
            if event.event_type.identifier == "filesystem.created" and modified_dates and date > min(modified_dates):
                comments.append("Création postérieure à la modification du fichier.")
            if event.event_type.identifier == "filesystem.modified" and created_dates and date < max(created_dates):
                comments.append("Modification antérieure à la création du fichier.")
            marked.append(
                replace(
                    event, comment=" ".join(comments) or event.comment, is_anomaly=bool(comments) or event.is_anomaly
                )
            )
        return tuple(marked)


def build_default_manager(metadata_manager: MetadataManager) -> TimelineManager:
    """Construit le registre initial ; de nouvelles sources s'ajoutent ici ou par injection."""
    return TimelineManager((ImageExifTimelineExtractor(metadata_manager), FilesystemTimelineExtractor()))
