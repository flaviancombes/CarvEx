"""Point d'extension futur pour les métadonnées audio."""

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataResult


class AudioMetadataExtractor(BaseMetadataExtractor):
    def supports(self, file_record: FileRecord) -> bool:
        return False

    def extract(self, file_record: FileRecord) -> MetadataResult:
        return MetadataResult.unavailable()
