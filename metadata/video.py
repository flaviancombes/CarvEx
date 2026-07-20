"""Point d'extension futur pour les métadonnées vidéo."""

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataResult


class VideoMetadataExtractor(BaseMetadataExtractor):
    def supports(self, file_record: FileRecord) -> bool:
        return False

    def extract(self, file_record: FileRecord) -> MetadataResult:
        return MetadataResult.unavailable()
