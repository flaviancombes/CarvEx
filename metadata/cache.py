"""Cache mémoire des résultats de métadonnées, indexé par fichier."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metadata.base import MetadataResult


class MetadataCache:
    """Évite toute nouvelle extraction pour un fichier déjà sélectionné."""

    def __init__(self) -> None:
        self._entries: dict[str, MetadataResult] = {}

    def get(self, file_record: Mapping[str, Any]) -> MetadataResult | None:
        return self._entries.get(self.key_for(file_record))

    def set(self, file_record: Mapping[str, Any], result: MetadataResult) -> None:
        self._entries[self.key_for(file_record)] = result

    @staticmethod
    def key_for(file_record: Mapping[str, Any]) -> str:
        return str(file_record.get("output") or file_record.get("source_path") or file_record.get("sha256") or file_record.get("name") or "")
