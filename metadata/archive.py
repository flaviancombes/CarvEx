"""Métadonnées d'archives bornées et sans extraction de contenu."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataCategory, MetadataConfidence, MetadataField


class ArchiveMetadataExtractor(BaseMetadataExtractor):
    provider_id = "stdlib.archive"
    priority = 100
    MAX_LISTED_ENTRIES = 100
    _SUFFIXES = {".zip", ".apk", ".tar", ".gz", ".tgz", ".bz2", ".xz"}

    def supports(self, file_record: FileRecord) -> bool:
        path = self.existing_path(file_record)
        mime = str(file_record.get("mime") or "").casefold()
        return self._suffix(file_record, path) in self._SUFFIXES or "zip" in mime or "tar" in mime

    def extract(self, file_record: FileRecord) -> tuple[MetadataField, ...]:
        path = self.existing_path(file_record)
        if path is None:
            return ()
        try:
            if zipfile.is_zipfile(path):
                return tuple(self._zip_fields(path))
            if tarfile.is_tarfile(path):
                return tuple(self._tar_fields(path))
        except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError):
            return ()
        return ()

    def _zip_fields(self, path: Path) -> list[MetadataField]:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries[: self.MAX_LISTED_ENTRIES]]
            compressed = sum(entry.compress_size for entry in entries)
            uncompressed = sum(entry.file_size for entry in entries)
            encrypted = any(entry.flag_bits & 0x1 for entry in entries)
            methods = sorted({self._compression_name(entry.compress_type) for entry in entries})
            crcs = ", ".join(f"{entry.CRC:08x}" for entry in entries[: self.MAX_LISTED_ENTRIES])
            fields = [
                self._field("archive.entries", "Entrées", len(entries), 10),
                self._field("archive.compressed_size", "Taille compressée", compressed, 20),
                self._field("archive.uncompressed_size", "Taille décompressée", uncompressed, 30),
                self._field(
                    "archive.encrypted", "Chiffrement", "Oui" if encrypted else "Non", 40, MetadataCategory.FORENSIC
                ),
                self._field("archive.compression", "Compression", ", ".join(methods), 45),
            ]
            if crcs:
                fields.append(self._field("archive.crc", "CRC (aperçu)", crcs, 46, MetadataCategory.FORENSIC))
            if archive.comment:
                fields.append(
                    self._field("archive.comment", "Commentaire", archive.comment.decode(errors="replace"), 50)
                )
            if names:
                fields.append(self._field("archive.contents", "Contenu (aperçu)", "\n".join(names), 60))
            return fields

    def _tar_fields(self, path: Path) -> list[MetadataField]:
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            names = [member.name for member in members[: self.MAX_LISTED_ENTRIES]]
            fields = [self._field("archive.entries", "Entrées", len(members), 10)]
            if names:
                fields.append(self._field("archive.contents", "Contenu (aperçu)", "\n".join(names), 60))
            return fields

    @staticmethod
    def _compression_name(value: int) -> str:
        return {
            zipfile.ZIP_STORED: "stockée",
            zipfile.ZIP_DEFLATED: "deflate",
            zipfile.ZIP_BZIP2: "bzip2",
            zipfile.ZIP_LZMA: "lzma",
        }.get(value, str(value))

    @staticmethod
    def _suffix(file_record: FileRecord, path: Path | None) -> str:
        return (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).casefold()

    @staticmethod
    def _field(
        identifier: str,
        label: str,
        value: str | int,
        order: int,
        category: MetadataCategory = MetadataCategory.ARCHIVES,
    ) -> MetadataField:
        return MetadataField(
            identifier,
            category,
            label,
            value,
            source="stdlib.archive",
            confidence=MetadataConfidence.HIGH,
            display_order=order,
        )
