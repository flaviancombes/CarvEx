"""Extraction de métadonnées image et EXIF via Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import ExifTags, Image

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataGroup, MetadataItem, MetadataResult


class ImageMetadataExtractor(BaseMetadataExtractor):
    """Extrait les propriétés générales, EXIF et GPS des formats image pris en charge."""

    EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".gif"}
    ORIENTATIONS = {1: "Haut gauche", 2: "Haut droite", 3: "Bas droite", 4: "Bas gauche", 5: "Gauche haut", 6: "Droite haut", 7: "Droite bas", 8: "Gauche bas"}

    def supports(self, file_record: FileRecord) -> bool:
        mime = str(file_record.get("mime") or "").lower()
        path = self.existing_path(file_record)
        extension = (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).lower()
        return mime.startswith("image/") or extension in self.EXTENSIONS

    def extract(self, file_record: FileRecord) -> MetadataResult:
        path = self.existing_path(file_record)
        if path is None:
            return MetadataResult.unavailable("Métadonnées indisponibles : fichier inaccessible.")

        with Image.open(path) as image:
            general = self._general_items(image)
            exif = image.getexif()
            exif_items = self._exif_items(exif)
            gps_items = self._gps_items(exif)

        groups = [MetadataGroup("Image", tuple(general))]
        indicators: list[str] = []
        if exif_items:
            groups.append(MetadataGroup("EXIF", tuple(exif_items)))
            indicators.append("📷 EXIF")
        if gps_items:
            groups.append(MetadataGroup("GPS", tuple(gps_items)))
            indicators.append("📍 GPS")
        if any(item.label == "Logiciel" for item in exif_items):
            indicators.append("🛠 Logiciel")
        return MetadataResult(tuple(groups), tuple(indicators))

    def _general_items(self, image: Image.Image) -> list[MetadataItem]:
        items = [
            MetadataItem("Dimensions", f"{image.width} × {image.height}"),
            MetadataItem("Mode couleur", image.mode),
            MetadataItem("Profondeur", self._bit_depth(image.mode, image.info)),
        ]
        dpi = image.info.get("dpi")
        if isinstance(dpi, tuple) and len(dpi) >= 2:
            items.append(MetadataItem("Résolution", f"{self._number(dpi[0])} × {self._number(dpi[1])} DPI"))
        return items

    def _exif_items(self, exif) -> list[MetadataItem]:
        if not exif:
            return []
        values = {
            "Marque": self._tag(exif, "Make"),
            "Modèle": self._tag(exif, "Model"),
            "Logiciel": self._tag(exif, "Software"),
            "Orientation": self._orientation(self._tag(exif, "Orientation")),
            "Date de prise de vue": self._exif_tag(exif, "DateTimeOriginal"),
            "Date de numérisation": self._exif_tag(exif, "DateTimeDigitized"),
            "Objectif": self._exif_tag(exif, "LensModel"),
            "Focale": self._unit(self._exif_tag(exif, "FocalLength"), " mm"),
            "Ouverture": self._aperture(self._exif_tag(exif, "FNumber")),
            "Vitesse": self._exif_tag(exif, "ExposureTime"),
            "ISO": self._exif_tag(exif, "ISOSpeedRatings"),
            "Flash": self._flash(self._exif_tag(exif, "Flash")),
            "Balance des blancs": self._white_balance(self._exif_tag(exif, "WhiteBalance")),
            "Compensation d'exposition": self._unit(self._exif_tag(exif, "ExposureBiasValue"), " EV"),
            "Mode d'exposition": self._exposure_mode(self._exif_tag(exif, "ExposureMode")),
        }
        return [MetadataItem(label, self._string(value)) for label, value in values.items() if value not in (None, "")]

    def _gps_items(self, exif) -> list[MetadataItem]:
        try:
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        except (AttributeError, KeyError, TypeError, ValueError):
            return []
        if not gps:
            return []
        latitude = self._decimal_coordinates(gps.get(2), gps.get(1))
        longitude = self._decimal_coordinates(gps.get(4), gps.get(3))
        altitude = self._ratio(gps.get(6))
        items: list[MetadataItem] = []
        if latitude is not None:
            items.append(MetadataItem("Latitude", f"{latitude:.5f}"))
        if longitude is not None:
            items.append(MetadataItem("Longitude", f"{longitude:.5f}"))
        if altitude is not None:
            if gps.get(5) == 1:
                altitude = -altitude
            items.append(MetadataItem("Altitude", f"{altitude:.2f} m"))
        return items

    @staticmethod
    def _tag(exif, name: str):
        tag_id = next((tag for tag, label in ExifTags.TAGS.items() if label == name), None)
        return exif.get(tag_id) if tag_id is not None else None

    def _exif_tag(self, exif, name: str):
        try:
            values = exif.get_ifd(ExifTags.IFD.Exif)
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        tag_id = next((tag for tag, label in ExifTags.TAGS.items() if label == name), None)
        return values.get(tag_id) if tag_id is not None else None

    @staticmethod
    def _bit_depth(mode: str, info: dict) -> str:
        known = {"1": 1, "L": 8, "P": 8, "LA": 16, "RGB": 24, "RGBA": 32, "CMYK": 32, "I": 32, "F": 32, "I;16": 16}
        bits = info.get("bits")
        if bits:
            return f"{bits} bits"
        return f"{known.get(mode, 8)} bits"

    @staticmethod
    def _ratio(value) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError, ZeroDivisionError):
            if isinstance(value, tuple) and len(value) == 2 and value[1]:
                return value[0] / value[1]
        return None

    def _decimal_coordinates(self, coordinate, reference) -> float | None:
        if not coordinate or len(coordinate) != 3:
            return None
        parts = [self._ratio(part) for part in coordinate]
        if any(part is None for part in parts):
            return None
        value = parts[0] + parts[1] / 60 + parts[2] / 3600
        return -value if str(reference).upper() in {"S", "W"} else value

    @staticmethod
    def _number(value) -> str:
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:.2f}"

    def _unit(self, value, unit: str) -> str | None:
        number = self._ratio(value)
        return f"{self._number(number)}{unit}" if number is not None else None

    def _aperture(self, value) -> str | None:
        number = self._ratio(value)
        return f"f/{self._number(number)}" if number is not None else None

    def _orientation(self, value) -> str | None:
        return self._enum(value, self.ORIENTATIONS)

    @staticmethod
    def _flash(value) -> str | None:
        return ImageMetadataExtractor._enum(value, {0: "Non déclenché", 1: "Déclenché"})

    @staticmethod
    def _white_balance(value) -> str | None:
        return ImageMetadataExtractor._enum(value, {0: "Automatique", 1: "Manuelle"})

    @staticmethod
    def _exposure_mode(value) -> str | None:
        return ImageMetadataExtractor._enum(value, {0: "Automatique", 1: "Manuel", 2: "Bracketing"})

    @staticmethod
    def _enum(value, labels: dict[int, str]) -> str | None:
        if value is None:
            return None
        try:
            return labels.get(int(value), str(value))
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _string(value) -> str:
        return value.decode(errors="replace") if isinstance(value, bytes) else str(value)
