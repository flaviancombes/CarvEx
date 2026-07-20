"""Contrats communs des extracteurs de métadonnées."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FileRecord = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MetadataItem:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class MetadataGroup:
    title: str
    items: tuple[MetadataItem, ...]


@dataclass(frozen=True, slots=True)
class MetadataResult:
    groups: tuple[MetadataGroup, ...] = ()
    indicators: tuple[str, ...] = ()
    unavailable_message: str | None = None

    @classmethod
    def unavailable(cls, message: str = "Métadonnées indisponibles.") -> "MetadataResult":
        return cls(indicators=("⚠ Aucune métadonnée",), unavailable_message=message)


class BaseMetadataExtractor(ABC):
    """Base stable pour tout extracteur ajouté ultérieurement."""

    @abstractmethod
    def supports(self, file_record: FileRecord) -> bool:
        """Indique si l'extracteur peut traiter cet enregistrement."""

    @abstractmethod
    def extract(self, file_record: FileRecord) -> MetadataResult:
        """Extrait les métadonnées sans modifier le fichier source."""

    @staticmethod
    def existing_path(file_record: FileRecord) -> Path | None:
        """Retourne le premier chemin local disponible, exporté puis source."""
        for field in ("output", "source_path"):
            value = file_record.get(field)
            if value:
                path = Path(str(value))
                if path.is_file():
                    return path
        return None
