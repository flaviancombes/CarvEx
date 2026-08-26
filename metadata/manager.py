"""Orchestration, fusion et cache des providers de métadonnées."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from PIL import UnidentifiedImageError

from metadata.archive import ArchiveMetadataExtractor
from metadata.audio import AudioMetadataExtractor
from metadata.base import (
    BaseMetadataExtractor,
    FileRecord,
    MetadataConfidence,
    MetadataField,
    MetadataResult,
)
from metadata.cache import MetadataCache
from metadata.executable import ExecutableMetadataExtractor
from metadata.generic import GenericMetadataExtractor
from metadata.image import ImageMetadataExtractor
from metadata.office import OfficeMetadataExtractor
from metadata.pdf import PdfMetadataExtractor
from metadata.registry import MetadataProviderRegistry
from metadata.store import MetadataStore
from metadata.video import VideoMetadataExtractor

LOGGER = logging.getLogger(__name__)
_CONFIDENCE_ORDER = {
    MetadataConfidence.LOW: 0,
    MetadataConfidence.MEDIUM: 1,
    MetadataConfidence.HIGH: 2,
}


class MetadataManager:
    """Orchestre les providers sans connaissance de l'interface Qt.

    Tous les providers compatibles sont appelés. La fusion conserve une seule
    valeur par identifiant stable, choisie par priorité de provider puis niveau
    de confiance, et renvoie un ordre de présentation déterministe.
    """

    def __init__(
        self,
        extractors: Iterable[BaseMetadataExtractor] | MetadataProviderRegistry,
        cache: MetadataCache | None = None,
    ) -> None:
        self._registry = (
            extractors if isinstance(extractors, MetadataProviderRegistry) else MetadataProviderRegistry(extractors)
        )
        self._cache = cache or MetadataCache()
        self._store: MetadataStore | None = None
        self._store_writable = True

    def extract(self, file_record: FileRecord) -> MetadataResult:
        """Retourne le résultat en cache ou agrège les providers compatibles."""
        cached = self._cache.get(file_record)
        if cached is not None:
            return cached

        file_id = self._cache.key_for(file_record)
        if self._store is not None:
            stored = self._store.get(file_id)
            if stored is not None:
                self._cache.set(file_record, stored)
                return stored

        candidates: dict[str, tuple[MetadataField, int]] = {}
        for provider in self._providers_for(file_record):
            try:
                fields = self._as_fields(provider.extract(file_record))
            except Exception as error:  # Un fichier corrompu ne doit jamais déstabiliser l'UI.
                self._log_provider_error(error, file_record)
                continue
            for field in fields:
                self._merge(candidates, field, provider.priority)

        result = self._build_result(candidates)
        self._cache.set(file_record, result)
        if self._store is not None and self._store_writable:
            self._store.set(file_id, result)
        return result

    def cached_or_stored(self, file_record: FileRecord) -> MetadataResult | None:
        """Return known metadata without invoking a provider or reading the file."""
        cached = self._cache.get(file_record)
        if cached is not None:
            return cached
        if self._store is None:
            return None
        stored = self._store.get(self._cache.key_for(file_record))
        if stored is not None:
            self._cache.set(file_record, stored)
        return stored

    def extract_transient(self, file_record: FileRecord) -> MetadataResult:
        """Extrait sans écrire cache ni Store, réservé aux workers purs."""
        candidates: dict[str, tuple[MetadataField, int]] = {}
        for provider in self._providers_for(file_record):
            try:
                for field in self._as_fields(provider.extract(file_record)):
                    self._merge(candidates, field, provider.priority)
            except Exception as error:
                self._log_provider_error(error, file_record)
        return self._build_result(candidates)

    @property
    def cache(self) -> MetadataCache:
        """Expose le cache de lecture aux projections Qt sans exposer les providers."""
        return self._cache

    @property
    def index(self):
        """Expose l'index persistant lorsque le projet actif en possède un."""
        return None if self._store is None else self._store.index

    def attach_store(self, store: MetadataStore) -> None:
        self._store = store
        self._store_writable = True
        self._cache.clear()

    def detach_store(self) -> None:
        self._store = None
        self._store_writable = True
        self._cache.clear()

    def set_store_writable(self, writable: bool) -> None:
        """Réserve les écritures persistantes au commit d'indexation lorsqu'il est actif."""
        self._store_writable = writable

    def _providers_for(self, file_record: FileRecord) -> tuple[BaseMetadataExtractor, ...]:
        supported: list[BaseMetadataExtractor] = []
        for provider in self._registry.providers:
            try:
                if provider.supports(file_record):
                    supported.append(provider)
            except Exception as error:
                self._log_provider_error(error, file_record)
        return tuple(supported)

    @staticmethod
    def _as_fields(result: Iterable[MetadataField] | MetadataResult) -> tuple[MetadataField, ...]:
        """Accepte temporairement MetadataResult pour les providers historiques."""
        if isinstance(result, MetadataResult):
            return result.fields
        fields = tuple(result)
        if not all(isinstance(field, MetadataField) for field in fields):
            raise TypeError("Un provider doit retourner des MetadataField.")
        return fields

    @staticmethod
    def _merge(candidates: dict[str, tuple[MetadataField, int]], field: MetadataField, priority: int) -> None:
        current = candidates.get(field.identifier)
        if current is None:
            candidates[field.identifier] = (field, priority)
            return
        current_field, current_priority = current
        if priority > current_priority or (
            priority == current_priority
            and _CONFIDENCE_ORDER[field.confidence] > _CONFIDENCE_ORDER[current_field.confidence]
        ):
            candidates[field.identifier] = (field, priority)

    @staticmethod
    def _build_result(candidates: dict[str, tuple[MetadataField, int]]) -> MetadataResult:
        fields = tuple(sorted((field for field, _ in candidates.values()), key=lambda field: field.sort_key))
        if not fields:
            return MetadataResult.unavailable()
        identifiers = {field.identifier for field in fields}
        indicators: list[str] = []
        if any(field.category.value == "exif" and not field.identifier.startswith("exif.gps.") for field in fields):
            indicators.append("📷 EXIF")
        if any(field.identifier.startswith("exif.gps.") for field in fields):
            indicators.append("📍 GPS")
        if "exif.software" in identifiers:
            indicators.append("🛠 Logiciel")
        return MetadataResult(fields=fields, indicators=indicators)

    @staticmethod
    def _log_provider_error(error: Exception, file_record: FileRecord) -> None:
        if MetadataManager._is_expected_image_error(error):
            LOGGER.debug("Métadonnées indisponibles pour une image corrompue %s: %s", file_record.get("name"), error)
        else:
            LOGGER.exception("Extraction de métadonnées impossible pour %s", file_record.get("name"))

    @staticmethod
    def _is_expected_image_error(error: Exception) -> bool:
        """Identifie les erreurs Pillow normales sur des fichiers PhotoRec corrompus."""
        if isinstance(error, UnidentifiedImageError):
            return True
        if not isinstance(error, OSError):
            return False
        message = str(error).casefold()
        return "broken data stream" in message or "unrecognized data stream" in message


def build_default_manager() -> MetadataManager:
    """Construit le registre initial ; les extensions s'enregistrent localement."""
    return MetadataManager(
        MetadataProviderRegistry(
            (
                ImageMetadataExtractor(),
                PdfMetadataExtractor(),
                OfficeMetadataExtractor(),
                VideoMetadataExtractor(),
                AudioMetadataExtractor(),
                ArchiveMetadataExtractor(),
                ExecutableMetadataExtractor(),
                GenericMetadataExtractor(),
            )
        )
    )
