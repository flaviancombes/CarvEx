"""Extracteur de repli pour les types non encore pris en charge."""

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataResult


class GenericMetadataExtractor(BaseMetadataExtractor):
    def supports(self, file_record: FileRecord) -> bool:
        return True

    def extract(self, file_record: FileRecord) -> MetadataResult:
        return MetadataResult.unavailable()
