"""Métadonnées conteneur MP4/MOV via Mutagen, sans recours au lecteur Qt."""

from __future__ import annotations

from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataCategory, MetadataConfidence, MetadataField


class VideoMetadataExtractor(BaseMetadataExtractor):
    provider_id = "mutagen.video"
    priority = 100
    _SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv", ".flv"}

    def supports(self, file_record: FileRecord) -> bool:
        path = self.existing_path(file_record)
        return (
            str(file_record.get("mime") or "").casefold().startswith("video/")
            or self._suffix(file_record, path) in self._SUFFIXES
        )

    def extract(self, file_record: FileRecord) -> tuple[MetadataField, ...]:
        path = self.existing_path(file_record)
        if path is None:
            return ()
        try:
            media = MutagenFile(path, easy=False)
            if media is None:
                return ()
            fields = self._technical_fields(media)
            fields.extend(self._tag_fields(getattr(media, "tags", None)))
            return tuple(fields)
        except (MutagenError, OSError, ValueError, TypeError):
            return ()

    def _technical_fields(self, media) -> list[MetadataField]:
        info = getattr(media, "info", None)
        if info is None:
            return []
        values = (
            ("video.duration", "Durée", self._duration(getattr(info, "length", None)), 10),
            ("video.codec", "Codec", media.__class__.__name__, 20),
            ("video.bitrate", "Débit", self._bitrate(getattr(info, "bitrate", None)), 30),
        )
        return [self._field(identifier, label, value, order) for identifier, label, value, order in values if value]

    def _tag_fields(self, tags) -> list[MetadataField]:
        if not tags:
            return []
        values = (
            ("video.creation_date", "Date caméra", self._tag(tags, "©day", "date"), 100),
            ("video.camera_make", "Marque caméra", self._tag(tags, "©mak", "make"), 110),
            ("video.camera_model", "Modèle caméra", self._tag(tags, "©mod", "model"), 120),
            ("video.gps", "GPS", self._tag(tags, "©xyz", "location"), 130),
            ("video.rotation", "Rotation", self._tag(tags, "rotate", "rotation"), 140),
        )
        return [self._field(identifier, label, value, order) for identifier, label, value, order in values if value]

    @staticmethod
    def _tag(tags, *keys: str) -> str | None:
        for key in keys:
            value = tags.get(key)
            if value:
                if isinstance(value, (list, tuple)):
                    value = value[0]
                return str(value).strip()
        return None

    @staticmethod
    def _duration(value: object) -> str | None:
        return f"{float(value):.2f} s" if value is not None else None

    @staticmethod
    def _bitrate(value: object) -> str | None:
        return f"{int(value)} bit/s" if value else None

    @staticmethod
    def _suffix(file_record: FileRecord, path: Path | None) -> str:
        return (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).casefold()

    @staticmethod
    def _field(identifier: str, label: str, value: str, order: int) -> MetadataField:
        return MetadataField(
            identifier,
            MetadataCategory.VIDEO,
            label,
            value,
            source="mutagen.video",
            confidence=MetadataConfidence.MEDIUM,
            display_order=order,
        )
