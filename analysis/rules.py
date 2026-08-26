"""Règles d'artefacts extensibles basées uniquement sur les métadonnées."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from analysis.artifact import Artifact
from metadata.base import MetadataResult


class ArtifactRule(Protocol):
    """Contrat : une nouvelle règle s'ajoute au registre sans modifier les autres."""

    def evaluate(self, file_record: Mapping[str, object], metadata: MetadataResult) -> Iterable[Artifact]: ...


def _items(metadata: MetadataResult, group_title: str) -> dict[str, str]:
    for group in metadata.groups:
        if group.title == group_title:
            return {item.label: item.value for item in group.items}
    return {}


def _is_image(file_record: Mapping[str, object]) -> bool:
    return str(file_record.get("category") or "") == "Images" or str(file_record.get("mime") or "").lower().startswith(
        "image/"
    )


class ImageExifRule:
    def evaluate(self, file_record: Mapping[str, object], metadata: MetadataResult) -> Iterable[Artifact]:
        if _is_image(file_record) and _items(metadata, "EXIF"):
            yield Artifact("image.exif", "📷 EXIF", ("image.exif",))


class ImageGpsRule:
    def evaluate(self, file_record: Mapping[str, object], metadata: MetadataResult) -> Iterable[Artifact]:
        gps = _items(metadata, "GPS")
        if _is_image(file_record) and "Latitude" in gps and "Longitude" in gps:
            yield Artifact("image.gps", "📍 Coordonnées GPS", ("image.gps",))


class ImageCameraRule:
    SMARTPHONE_MARKERS = (
        "apple",
        "iphone",
        "samsung",
        "google",
        "pixel",
        "huawei",
        "xiaomi",
        "oneplus",
        "sony xperia",
        "nokia",
        "motorola",
        "oppo",
        "vivo",
    )

    def evaluate(self, file_record: Mapping[str, object], metadata: MetadataResult) -> Iterable[Artifact]:
        if not _is_image(file_record):
            return
        exif = _items(metadata, "EXIF")
        make, model = exif.get("Marque", "").strip(), exif.get("Modèle", "").strip()
        identity = " ".join(value for value in (make, model) if value)
        if not identity:
            return
        is_smartphone = any(marker in identity.casefold() for marker in self.SMARTPHONE_MARKERS)
        if is_smartphone:
            yield Artifact("image.smartphone", f"📱 {identity}", ("image.smartphone",))
        else:
            yield Artifact("image.camera", f"📷 {identity}", ("image.camera",))


class ImageSoftwareRule:
    def evaluate(self, file_record: Mapping[str, object], metadata: MetadataResult) -> Iterable[Artifact]:
        if not _is_image(file_record):
            return
        software = _items(metadata, "EXIF").get("Logiciel", "").strip()
        if software:
            yield Artifact("image.modified", f"🛠 {software}", ("image.modified",))


class ImageNoMetadataRule:
    def evaluate(self, file_record: Mapping[str, object], metadata: MetadataResult) -> Iterable[Artifact]:
        if _is_image(file_record) and not _items(metadata, "EXIF") and not _items(metadata, "GPS"):
            yield Artifact("image.no_exif", "⚠ Métadonnées absentes", ("image.no_exif",), "warning")


DEFAULT_RULES: tuple[ArtifactRule, ...] = (
    ImageExifRule(),
    ImageGpsRule(),
    ImageCameraRule(),
    ImageSoftwareRule(),
    ImageNoMetadataRule(),
)
