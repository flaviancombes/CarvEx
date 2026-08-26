"""Cache mémoire des résultats de métadonnées, indexé par fichier."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import Any

from core.file_identity import require_file_id
from metadata.base import MetadataResult


class MetadataCache:
    """Évite toute nouvelle extraction pour un fichier déjà sélectionné."""

    def __init__(self) -> None:
        self._entries: dict[str, MetadataResult] = {}
        self._lock = RLock()

    def get(self, file_record: Mapping[str, Any]) -> MetadataResult | None:
        with self._lock:
            return self._entries.get(self.key_for(file_record))

    def set(self, file_record: Mapping[str, Any], result: MetadataResult) -> None:
        with self._lock:
            self._entries[self.key_for(file_record)] = result

    def clear(self) -> None:
        """Libère les accélérateurs mémoire lors d'un changement de projet."""
        with self._lock:
            self._entries.clear()

    @staticmethod
    def key_for(file_record: Mapping[str, Any]) -> str:
        """Retourne exclusivement l'identité immuable attribuée à l'import."""
        return require_file_id(file_record)
