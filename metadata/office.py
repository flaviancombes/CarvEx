"""Point d'extension futur pour les documents Office."""

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataResult


class OfficeMetadataExtractor(BaseMetadataExtractor):
    def supports(self, file_record: FileRecord) -> bool:
        return False

    def extract(self, file_record: FileRecord) -> MetadataResult:
        return MetadataResult.unavailable()
