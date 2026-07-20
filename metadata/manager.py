"""Sélection et mise en cache des extracteurs de métadonnées."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataResult
from metadata.cache import MetadataCache
from metadata.generic import GenericMetadataExtractor
from metadata.image import ImageMetadataExtractor

LOGGER = logging.getLogger(__name__)


class MetadataManager:
    """Orchestre les extracteurs sans connaissance de l'interface Qt."""

    def __init__(self, extractors: Iterable[BaseMetadataExtractor], cache: MetadataCache | None = None) -> None:
        self._extractors = tuple(extractors)
        self._cache = cache or MetadataCache()

    def extract(self, file_record: FileRecord) -> MetadataResult:
        """Retourne un résultat en cache ou extrait les données à la demande."""
        cached = self._cache.get(file_record)
        if cached is not None:
            return cached

        try:
            extractor = next(item for item in self._extractors if item.supports(file_record))
            result = extractor.extract(file_record)
        except Exception:  # Un fichier corrompu ne doit jamais déstabiliser l'UI.
            LOGGER.exception("Extraction de métadonnées impossible pour %s", file_record.get("name"))
            result = MetadataResult.unavailable("Métadonnées indisponibles.")

        self._cache.set(file_record, result)
        return result


def build_default_manager() -> MetadataManager:
    """Construit le registre initial ; de futurs extracteurs peuvent être enregistrés."""
    return MetadataManager((ImageMetadataExtractor(), GenericMetadataExtractor()))
