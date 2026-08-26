"""Sources d'événements temporels enregistrables sans dépendance Qt."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

from metadata.manager import MetadataManager
from timeline.event import Confidence, TimelineEvent
from timeline.source import (
    EXIF,
    EXIF_CAPTURED,
    EXIF_DIGITIZED,
    EXIF_MODIFIED,
    FILE_ACCESSED,
    FILE_CREATED,
    FILE_MODIFIED,
    FILESYSTEM,
)


class TimelineExtractor(Protocol):
    """Contrat O/C pour les futures sources (PDF, Registry, journaux, etc.)."""

    def extract(self, file_record: Mapping[str, object]) -> Iterable[TimelineEvent]: ...


class ImageExifTimelineExtractor:
    """Convertit les dates déjà extraites par le framework de métadonnées."""

    DATE_FIELDS = (
        ("Date de prise de vue", EXIF_CAPTURED),
        ("Date de numérisation", EXIF_DIGITIZED),
        ("Date de modification EXIF", EXIF_MODIFIED),
    )
    FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")

    def __init__(self, metadata_manager: MetadataManager) -> None:
        self._metadata_manager = metadata_manager

    def extract(self, file_record: Mapping[str, object]) -> Iterable[TimelineEvent]:
        result = self._metadata_manager.cached_or_stored(file_record)
        if result is None:
            return
        values = {item.label: item.value for group in result.groups if group.title == "EXIF" for item in group.items}
        for label, event_type in self.DATE_FIELDS:
            date = self._parse(values.get(label))
            if date is not None:
                yield TimelineEvent(event_type, date, EXIF, Confidence.HIGH, metadata=values)

    @classmethod
    def _parse(cls, value: str | None) -> datetime | None:
        if not value:
            return None
        for date_format in cls.FORMATS:
            try:
                return datetime.strptime(value.strip(), date_format)
            except (TypeError, ValueError):
                continue
        return None


class FilesystemTimelineExtractor:
    """Expose les horodatages disponibles localement, sans interprétation."""

    def extract(self, file_record: Mapping[str, object]) -> Iterable[TimelineEvent]:
        path = self._existing_path(file_record)
        if path is None:
            return
        stat = path.stat()
        yield TimelineEvent(
            FILE_CREATED, datetime.fromtimestamp(stat.st_ctime).astimezone(), FILESYSTEM, Confidence.MEDIUM
        )
        yield TimelineEvent(
            FILE_MODIFIED, datetime.fromtimestamp(stat.st_mtime).astimezone(), FILESYSTEM, Confidence.HIGH
        )
        yield TimelineEvent(
            FILE_ACCESSED, datetime.fromtimestamp(stat.st_atime).astimezone(), FILESYSTEM, Confidence.LOW
        )

    @staticmethod
    def _existing_path(file_record: Mapping[str, object]) -> Path | None:
        for field in ("output", "source_path"):
            value = file_record.get(field)
            if value:
                path = Path(str(value))
                if path.is_file():
                    return path
        return None
