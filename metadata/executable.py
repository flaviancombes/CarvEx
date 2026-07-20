"""Point d'extension futur pour les métadonnées d'exécutables."""

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataResult


class ExecutableMetadataExtractor(BaseMetadataExtractor):
    def supports(self, file_record: FileRecord) -> bool:
        return False

    def extract(self, file_record: FileRecord) -> MetadataResult:
        return MetadataResult.unavailable()
