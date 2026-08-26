"""Métadonnées audio via Mutagen."""

from __future__ import annotations

from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataCategory, MetadataConfidence, MetadataField


class AudioMetadataExtractor(BaseMetadataExtractor):
    provider_id = "mutagen.audio"
    priority = 100
    _SUFFIXES = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma", ".aiff"}

    def supports(self, file_record: FileRecord) -> bool:
        path = self.existing_path(file_record)
        return (
            str(file_record.get("mime") or "").casefold().startswith("audio/")
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
            fields.extend(self._tag_fields(media.tags))
            return tuple(fields)
        except (MutagenError, OSError, ValueError, TypeError):
            return ()

    def _technical_fields(self, media) -> list[MetadataField]:
        info = getattr(media, "info", None)
        if info is None:
            return []
        values = (
            ("audio.duration", "Durée", self._duration(getattr(info, "length", None)), 10),
            ("audio.codec", "Codec", media.__class__.__name__, 20),
            ("audio.bitrate", "Débit", self._bitrate(getattr(info, "bitrate", None)), 30),
            ("audio.sample_rate", "Fréquence", self._hertz(getattr(info, "sample_rate", None)), 40),
            ("audio.channels", "Canaux", getattr(info, "channels", None), 50),
        )
        return [
            self._field(identifier, label, value, order)
            for identifier, label, value, order in values
            if value not in (None, "")
        ]

    def _tag_fields(self, tags) -> list[MetadataField]:
        if not tags:
            return []
        values = {
            "audio.artist": ("Artiste", self._tag(tags, "artist", "TPE1", "©ART")),
            "audio.album": ("Album", self._tag(tags, "album", "TALB", "©alb")),
            "audio.genre": ("Genre", self._tag(tags, "genre", "TCON", "©gen")),
            "audio.year": ("Année", self._tag(tags, "date", "year", "TDRC", "©day")),
            "audio.title": ("Titre", self._tag(tags, "title", "TIT2", "©nam")),
            "audio.replaygain": ("ReplayGain", self._tag(tags, "replaygain_track_gain", "REPLAYGAIN_TRACK_GAIN")),
        }
        fields = [
            self._field(identifier, label, value, 100 + index * 10)
            for index, (identifier, (label, value)) in enumerate(values.items())
            if value
        ]
        if self._has_artwork(tags):
            fields.append(self._field("audio.artwork", "Jaquette", "Présente", 200))
        return fields

    @staticmethod
    def _tag(tags, *keys: str) -> str | None:
        for key in keys:
            value = tags.get(key)
            if value:
                if isinstance(value, (list, tuple)):
                    value = value[0]
                text = str(value).strip()
                if text:
                    return text
        return None

    @staticmethod
    def _has_artwork(tags) -> bool:
        return any(str(key).casefold().startswith(("apic", "covr", "metadata_block_picture")) for key in tags.keys())

    @staticmethod
    def _duration(value: object) -> str | None:
        return f"{float(value):.2f} s" if value is not None else None

    @staticmethod
    def _bitrate(value: object) -> str | None:
        return f"{int(value)} bit/s" if value else None

    @staticmethod
    def _hertz(value: object) -> str | None:
        return f"{int(value)} Hz" if value else None

    @staticmethod
    def _suffix(file_record: FileRecord, path: Path | None) -> str:
        return (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).casefold()

    @staticmethod
    def _field(identifier: str, label: str, value: str | int, order: int) -> MetadataField:
        return MetadataField(
            identifier,
            MetadataCategory.AUDIO,
            label,
            value,
            source="mutagen.audio",
            confidence=MetadataConfidence.HIGH,
            display_order=order,
        )
