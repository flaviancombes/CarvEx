"""Contrats typés du pipeline de métadonnées.

Les providers produisent uniquement des :class:`MetadataField`.  Les groupes
restent une projection de compatibilité pour les consommateurs Qt historiques;
ils ne sont jamais la donnée primaire du pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeAlias

FileRecord: TypeAlias = Mapping[str, Any]
MetadataScalar: TypeAlias = str | int | float | bool | datetime


class MetadataCategory(StrEnum):
    """Catégories indépendantes de toute vue ou provider."""

    GENERAL = "general"
    FILESYSTEM = "filesystem"
    EXIF = "exif"
    IPTC = "iptc"
    XMP = "xmp"
    VIDEO = "video"
    AUDIO = "audio"
    OFFICE = "office"
    PDF = "pdf"
    ARCHIVES = "archives"
    EXECUTABLE = "executable"
    FORENSIC = "forensic"


class MetadataValueType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATETIME = "datetime"


class MetadataConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_CATEGORY_ORDER = {category: index for index, category in enumerate(MetadataCategory)}
_CATEGORY_TITLES = {
    MetadataCategory.GENERAL: "Général",
    MetadataCategory.FILESYSTEM: "Système de fichiers",
    MetadataCategory.EXIF: "EXIF",
    MetadataCategory.IPTC: "IPTC",
    MetadataCategory.XMP: "XMP",
    MetadataCategory.VIDEO: "Vidéo",
    MetadataCategory.AUDIO: "Audio",
    MetadataCategory.OFFICE: "Office",
    MetadataCategory.PDF: "PDF",
    MetadataCategory.ARCHIVES: "Archives",
    MetadataCategory.EXECUTABLE: "Exécutable",
    MetadataCategory.FORENSIC: "Forensic",
}


@dataclass(frozen=True, slots=True)
class MetadataField:
    """Une métadonnée atomique, stable et indépendante de sa présentation."""

    identifier: str
    category: MetadataCategory
    display_name: str
    value: MetadataScalar
    value_type: MetadataValueType = MetadataValueType.TEXT
    unit: str | None = None
    source: str = ""
    confidence: MetadataConfidence = MetadataConfidence.MEDIUM
    display_order: int = 0

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("L'identifiant d'un champ de métadonnée est obligatoire.")
        if not self.display_name.strip():
            raise ValueError("Le nom affiché d'un champ de métadonnée est obligatoire.")
        if not self.source.strip():
            raise ValueError("La provenance d'un champ de métadonnée est obligatoire.")

    @property
    def display_value(self) -> str:
        """Valeur stablement formatée pour les projections existantes."""
        if isinstance(self.value, bool):
            text = "Oui" if self.value else "Non"
        else:
            text = str(self.value)
        return f"{text} {self.unit}" if self.unit else text

    @property
    def group_title(self) -> str:
        """Compatibilité de présentation ; les coordonnées restent groupées GPS."""
        if self.identifier.startswith("exif.gps."):
            return "GPS"
        if self.identifier.startswith("image."):
            return "Image"
        return _CATEGORY_TITLES[self.category]

    @property
    def sort_key(self) -> tuple[int, int, str, str]:
        return (_CATEGORY_ORDER[self.category], self.display_order, self.display_name.casefold(), self.identifier)


@dataclass(frozen=True, slots=True)
class MetadataItem:
    """Projection Qt historique d'un :class:`MetadataField`."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class MetadataGroup:
    """Projection Qt historique regroupant des champs typés."""

    title: str
    items: tuple[MetadataItem, ...]


@dataclass(frozen=True, slots=True, init=False)
class MetadataResult:
    """Résultat immuable dont ``fields`` est la seule donnée primaire.

    ``groups=`` reste accepté uniquement pour les consommateurs historiques et
    tests existants ; il est immédiatement converti en champs typés.
    """

    fields: tuple[MetadataField, ...]
    indicators: tuple[str, ...]
    unavailable_message: str | None

    def __init__(
        self,
        fields: Iterable[MetadataField] = (),
        indicators: Iterable[str] = (),
        unavailable_message: str | None = None,
        *,
        groups: Iterable[MetadataGroup] | None = None,
    ) -> None:
        typed_fields = tuple(fields)
        if groups is not None:
            if typed_fields:
                raise ValueError("Un résultat ne peut pas contenir simultanément fields et groups.")
            typed_fields = self._fields_from_groups(groups)
        object.__setattr__(self, "fields", typed_fields)
        object.__setattr__(self, "indicators", tuple(indicators))
        object.__setattr__(self, "unavailable_message", unavailable_message)

    @classmethod
    def unavailable(cls, message: str = "Métadonnées indisponibles.") -> MetadataResult:
        return cls(indicators=("⚠ Aucune métadonnée",), unavailable_message=message)

    @property
    def groups(self) -> tuple[MetadataGroup, ...]:
        """Projection déterministe pour les panels, règles et Timeline existants."""
        grouped: dict[str, list[MetadataItem]] = {}
        for field in sorted(self.fields, key=lambda item: item.sort_key):
            grouped.setdefault(field.group_title, []).append(MetadataItem(field.display_name, field.display_value))
        return tuple(MetadataGroup(title, tuple(items)) for title, items in grouped.items())

    @staticmethod
    def _fields_from_groups(groups: Iterable[MetadataGroup]) -> tuple[MetadataField, ...]:
        fields: list[MetadataField] = []
        category_by_title = {title.casefold(): category for category, title in _CATEGORY_TITLES.items()}
        category_by_title["gps"] = MetadataCategory.EXIF
        for group_index, group in enumerate(groups):
            category = category_by_title.get(group.title.casefold(), MetadataCategory.GENERAL)
            prefix = "exif.gps" if group.title.casefold() == "gps" else category.value
            for item_index, item in enumerate(group.items):
                identifier = f"{prefix}.legacy.{group_index}.{item_index}"
                fields.append(
                    MetadataField(
                        identifier=identifier,
                        category=category,
                        display_name=item.label,
                        value=item.value,
                        source="legacy.result",
                        display_order=item_index,
                    )
                )
        return tuple(fields)


class MetadataProvider(ABC):
    """Contrat commun : un provider déclare sa priorité et produit des champs."""

    provider_id = "metadata.provider"
    priority = 0

    @abstractmethod
    def supports(self, file_record: FileRecord) -> bool:
        """Indique si le provider peut traiter cet enregistrement."""

    @abstractmethod
    def extract(self, file_record: FileRecord) -> Iterable[MetadataField]:
        """Extrait des champs sans modifier le fichier source."""

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


# Alias de migration : les extensions existantes conservent leur point d'entrée.
BaseMetadataExtractor = MetadataProvider
