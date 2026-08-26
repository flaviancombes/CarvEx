"""Extracteur de repli pour les types non encore pris en charge."""

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataField


class GenericMetadataExtractor(BaseMetadataExtractor):
    """Provider terminal : il confirme l'absence de champ sans créer de donnée."""

    provider_id = "generic.unavailable"
    priority = -1000

    def supports(self, file_record: FileRecord) -> bool:
        return True

    def extract(self, file_record: FileRecord) -> tuple[MetadataField, ...]:
        return ()
