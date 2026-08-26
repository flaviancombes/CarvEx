"""Extraction typée et normalisée des métadonnées d'images avec Pillow."""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from PIL import ExifTags, Image, IptcImagePlugin

from metadata.base import (
    BaseMetadataExtractor,
    FileRecord,
    MetadataCategory,
    MetadataConfidence,
    MetadataField,
    MetadataValueType,
)


class ImageMetadataExtractor(BaseMetadataExtractor):
    """Extrait les structures réellement décodables par Pillow, sans données libres."""

    provider_id = "pillow.image"
    priority = 100
    EXTENSIONS = {
        ".arw",
        ".bmp",
        ".cr2",
        ".cr3",
        ".dng",
        ".gif",
        ".heic",
        ".heif",
        ".jpeg",
        ".jpg",
        ".nef",
        ".orf",
        ".png",
        ".raw",
        ".rw2",
        ".tif",
        ".tiff",
        ".webp",
    }
    ORIENTATIONS = {
        1: "Haut gauche",
        2: "Haut droite",
        3: "Bas droite",
        4: "Bas gauche",
        5: "Gauche haut",
        6: "Droite haut",
        7: "Droite bas",
        8: "Gauche bas",
    }
    _IPTC_NAMES = {
        (2, 5): ("iptc.object_name", "Nom de l'objet"),
        (2, 25): ("iptc.keywords", "Mots-clés"),
        (2, 55): ("iptc.date_created", "Date de création"),
        (2, 60): ("iptc.time_created", "Heure de création"),
        (2, 80): ("iptc.author", "Auteur"),
        (2, 85): ("iptc.author_title", "Fonction de l'auteur"),
        (2, 90): ("iptc.city", "Ville"),
        (2, 95): ("iptc.province", "Région"),
        (2, 100): ("iptc.country_code", "Code pays"),
        (2, 101): ("iptc.country", "Pays"),
        (2, 105): ("iptc.headline", "Titre"),
        (2, 110): ("iptc.credit", "Crédit"),
        (2, 115): ("iptc.source", "Source"),
        (2, 116): ("iptc.copyright", "Copyright"),
        (2, 120): ("iptc.caption", "Légende"),
        (2, 122): ("iptc.caption_writer", "Rédacteur de légende"),
    }
    _DATE_TAGS = {
        "DateTime": "exif.datetime_modified",
        "DateTimeOriginal": "exif.datetime_original",
        "DateTimeDigitized": "exif.datetime_digitized",
    }
    _OFFSET_TAGS = {
        "DateTime": "OffsetTime",
        "DateTimeOriginal": "OffsetTimeOriginal",
        "DateTimeDigitized": "OffsetTimeDigitized",
    }
    _MAX_PNG_CHUNK_BYTES = 4 * 1024 * 1024
    _MAX_PNG_TEXT_BYTES = 1 * 1024 * 1024

    def supports(self, file_record: FileRecord) -> bool:
        mime = str(file_record.get("mime") or "").casefold()
        path = self.existing_path(file_record)
        extension = (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).casefold()
        return mime.startswith("image/") or extension in self.EXTENSIONS

    def extract(self, file_record: FileRecord) -> tuple[MetadataField, ...]:
        path = self.existing_path(file_record)
        if path is None:
            return ()
        with Image.open(path) as image:
            exif = image.getexif()
            fields = [
                *self._general_fields(image),
                *self._exif_fields(exif, image.info.get("exif")),
                *self._gps_fields(exif),
                *self._iptc_fields(image),
                *self._xmp_fields(image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")),
                *self._format_fields(image, path),
                *self._icc_fields(image.info.get("icc_profile")),
            ]
        return tuple(sorted(fields, key=lambda field: field.sort_key))

    def _general_fields(self, image: Image.Image) -> list[MetadataField]:
        bits = self._bits_per_pixel(image)
        fields = [
            self._field("image.width", MetadataCategory.GENERAL, "Largeur", image.width, MetadataValueType.INTEGER, 10),
            self._field(
                "image.height", MetadataCategory.GENERAL, "Hauteur", image.height, MetadataValueType.INTEGER, 20
            ),
            self._field(
                "image.dimensions",
                MetadataCategory.GENERAL,
                "Dimensions",
                f"{image.width} × {image.height}",
                MetadataValueType.TEXT,
                30,
            ),
            self._field(
                "image.color_mode", MetadataCategory.GENERAL, "Mode couleur", image.mode, MetadataValueType.TEXT, 40
            ),
            self._field(
                "image.bits_per_pixel", MetadataCategory.GENERAL, "Bits par pixel", bits, MetadataValueType.INTEGER, 50
            ),
            self._field(
                "image.format",
                MetadataCategory.GENERAL,
                "Format",
                image.format or "Inconnu",
                MetadataValueType.TEXT,
                60,
            ),
        ]
        dpi = image.info.get("dpi")
        if isinstance(dpi, tuple) and len(dpi) >= 2:
            fields.extend(
                (
                    self._field(
                        "image.dpi_x",
                        MetadataCategory.GENERAL,
                        "DPI horizontal",
                        float(dpi[0]),
                        MetadataValueType.DECIMAL,
                        70,
                        "dpi",
                    ),
                    self._field(
                        "image.dpi_y",
                        MetadataCategory.GENERAL,
                        "DPI vertical",
                        float(dpi[1]),
                        MetadataValueType.DECIMAL,
                        80,
                        "dpi",
                    ),
                )
            )
        gamma = self._ratio(image.info.get("gamma"))
        if gamma is not None:
            fields.append(
                self._field("image.gamma", MetadataCategory.GENERAL, "Gamma", gamma, MetadataValueType.DECIMAL, 90)
            )
        return fields

    def _exif_fields(self, exif, image_exif: object) -> list[MetadataField]:
        if not exif:
            return []
        exif_ifd = self._exif_ifd(exif)
        fields: list[MetadataField] = []
        known = {
            "Make",
            "Model",
            "Software",
            "Orientation",
            "DateTime",
            "DateTimeOriginal",
            "DateTimeDigitized",
            "GPSInfo",
            "Copyright",
            "ColorSpace",
            "MakerNote",
        }
        simple = (
            ("exif.make", "Marque", self._tag(exif, "Make")),
            ("exif.model", "Modèle", self._tag(exif, "Model")),
            ("exif.software", "Logiciel", self._tag(exif, "Software")),
            ("exif.copyright", "Copyright", self._tag(exif, "Copyright")),
            ("exif.lens_model", "Objectif", self._tag(exif_ifd, "LensModel")),
            ("exif.artist", "Auteur", self._tag(exif, "Artist")),
        )
        for order, (identifier, label, value) in enumerate(simple, start=100):
            if value not in (None, ""):
                fields.append(
                    self._field(
                        identifier,
                        MetadataCategory.EXIF,
                        label,
                        self._string(value),
                        MetadataValueType.TEXT,
                        order * 10,
                    )
                )
        orientation = self._integer(self._tag(exif, "Orientation"))
        if orientation is not None:
            fields.extend(
                (
                    self._field(
                        "exif.orientation",
                        MetadataCategory.EXIF,
                        "Orientation",
                        orientation,
                        MetadataValueType.INTEGER,
                        170,
                    ),
                    self._field(
                        "exif.orientation_label",
                        MetadataCategory.EXIF,
                        "Orientation lisible",
                        self.ORIENTATIONS.get(orientation, str(orientation)),
                        MetadataValueType.TEXT,
                        171,
                    ),
                )
            )
        color_space = self._integer(self._tag(exif_ifd, "ColorSpace"))
        if color_space is not None:
            fields.append(
                self._field(
                    "exif.color_space", MetadataCategory.EXIF, "ColorSpace", color_space, MetadataValueType.INTEGER, 180
                )
            )
        fields.extend(self._date_fields(exif, exif_ifd))
        numeric = (
            ("exif.focal_length", "Focale", self._ratio(self._tag(exif_ifd, "FocalLength")), "mm"),
            ("exif.f_number", "Ouverture", self._ratio(self._tag(exif_ifd, "FNumber")), None),
            ("exif.exposure_time", "Temps d'exposition", self._ratio(self._tag(exif_ifd, "ExposureTime")), "s"),
            ("exif.iso", "ISO", self._ratio(self._tag(exif_ifd, "ISOSpeedRatings")), None),
            (
                "exif.exposure_bias",
                "Compensation d'exposition",
                self._ratio(self._tag(exif_ifd, "ExposureBiasValue")),
                "EV",
            ),
            ("exif.metering_mode", "Mode mesure", self._integer(self._tag(exif_ifd, "MeteringMode")), None),
            ("exif.white_balance", "Balance des blancs", self._integer(self._tag(exif_ifd, "WhiteBalance")), None),
            ("exif.exposure_mode", "Mode exposition", self._integer(self._tag(exif_ifd, "ExposureMode")), None),
            ("exif.flash", "Flash", self._integer(self._tag(exif_ifd, "Flash")), None),
        )
        for order, (identifier, label, value, unit) in enumerate(numeric, start=200):
            if value is not None:
                value_type = MetadataValueType.INTEGER if isinstance(value, int) else MetadataValueType.DECIMAL
                fields.append(
                    self._field(identifier, MetadataCategory.EXIF, label, value, value_type, order * 10, unit)
                )
        maker_note = self._tag(exif_ifd, "MakerNote")
        if maker_note:
            raw = bytes(maker_note) if not isinstance(maker_note, bytes) else maker_note
            fields.extend(
                (
                    self._field(
                        "exif.maker_note.sha256",
                        MetadataCategory.FORENSIC,
                        "MakerNotes SHA-256",
                        hashlib.sha256(raw).hexdigest(),
                        MetadataValueType.TEXT,
                        400,
                    ),
                    self._field(
                        "exif.maker_note.size",
                        MetadataCategory.FORENSIC,
                        "Taille MakerNotes",
                        len(raw),
                        MetadataValueType.INTEGER,
                        410,
                        "o",
                    ),
                )
            )
        fields.extend(self._thumbnail_fields(image_exif=image_exif, exif_ifd=exif_ifd))
        for tag, value in exif.items():
            name = ExifTags.TAGS.get(tag, f"Tag {tag}")
            if name in known or value in (None, ""):
                continue
            fields.append(self._raw_field("exif.raw", tag, name, value, 1_000 + int(tag)))
        for tag, value in exif_ifd.items():
            name = ExifTags.TAGS.get(tag, f"Exif tag {tag}")
            if name in known or value in (None, ""):
                continue
            fields.append(self._raw_field("exif.extended", tag, name, value, 2_000 + int(tag)))
        return fields

    def _date_fields(self, exif, exif_ifd) -> list[MetadataField]:
        fields: list[MetadataField] = []
        for order, (name, identifier) in enumerate(self._DATE_TAGS.items(), start=1):
            value = self._tag(exif_ifd, name) or self._tag(exif, name)
            parsed, assumed = self._parse_exif_datetime(value, self._tag(exif_ifd, self._OFFSET_TAGS[name]))
            if parsed is not None:
                fields.append(
                    self._field(
                        identifier, MetadataCategory.EXIF, name, parsed, MetadataValueType.DATETIME, 300 + order * 10
                    )
                )
                if assumed:
                    fields.append(
                        self._field(
                            f"{identifier}.timezone_assumed",
                            MetadataCategory.FORENSIC,
                            "Fuseau supposé UTC",
                            True,
                            MetadataValueType.BOOLEAN,
                            301 + order * 10,
                        )
                    )
        return fields

    def _gps_fields(self, exif) -> list[MetadataField]:
        try:
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        except (AttributeError, KeyError, TypeError, ValueError):
            return []
        if not gps:
            return []
        fields: list[MetadataField] = []
        latitude = self._decimal_coordinates(gps.get(2), gps.get(1))
        longitude = self._decimal_coordinates(gps.get(4), gps.get(3))
        altitude = self._ratio(gps.get(6))
        direction = self._ratio(gps.get(17))
        precision = self._ratio(gps.get(31)) or self._ratio(gps.get(11))
        speed = self._gps_speed_kmh(self._ratio(gps.get(13)), gps.get(12))
        values = (
            ("exif.gps.latitude", "Latitude", latitude, None),
            ("exif.gps.longitude", "Longitude", longitude, None),
            ("exif.gps.altitude", "Altitude", -altitude if altitude is not None and gps.get(5) == 1 else altitude, "m"),
            ("exif.gps.direction", "Direction", direction, "°"),
            ("exif.gps.speed", "Vitesse GPS", speed, "km/h"),
            ("exif.gps.accuracy", "Précision GPS", precision, "m"),
        )
        for order, (identifier, label, value, unit) in enumerate(values, start=1):
            if value is not None:
                fields.append(
                    self._field(
                        identifier,
                        MetadataCategory.EXIF,
                        label,
                        value,
                        MetadataValueType.DECIMAL,
                        500 + order * 10,
                        unit,
                    )
                )
        gps_datetime = self._gps_datetime(gps.get(29), gps.get(7))
        if gps_datetime is not None:
            fields.append(
                self._field(
                    "exif.gps.timestamp",
                    MetadataCategory.EXIF,
                    "Horodatage GPS",
                    gps_datetime,
                    MetadataValueType.DATETIME,
                    570,
                )
            )
        handled = {1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 16, 17, 29, 31}
        for tag, value in gps.items():
            if tag in handled or value in (None, ""):
                continue
            label = ExifTags.GPSTAGS.get(tag, f"GPS tag {tag}")
            fields.append(self._raw_field("exif.gps.raw", tag, label, value, 580 + int(tag)))
        return fields

    def _iptc_fields(self, image: Image.Image) -> list[MetadataField]:
        try:
            values = IptcImagePlugin.getiptcinfo(image) or {}
        except (OSError, SyntaxError, ValueError):
            return []
        fields: list[MetadataField] = []
        for index, (key, value) in enumerate(sorted(values.items()), start=1):
            if value in (None, b"", ""):
                continue
            identifier, label = self._IPTC_NAMES.get(key, (f"iptc.{key[0]}.{key[1]}", f"IPTC {key[0]}:{key[1]}"))
            text = ", ".join(self._string(item) for item in value) if isinstance(value, list) else self._string(value)
            parsed = self._parse_iptc_date(text) if identifier == "iptc.date_created" else None
            fields.append(
                self._field(
                    identifier,
                    MetadataCategory.IPTC,
                    label,
                    parsed if parsed is not None else text,
                    MetadataValueType.DATETIME if parsed is not None else MetadataValueType.TEXT,
                    600 + index * 10,
                )
            )
        return fields

    def _xmp_fields(self, raw: object) -> list[MetadataField]:
        if not raw:
            return []
        try:
            root = ElementTree.fromstring(raw if isinstance(raw, bytes) else str(raw).encode())
        except (ElementTree.ParseError, TypeError, ValueError):
            return []
        values: defaultdict[str, list[str]] = defaultdict(list)
        labels: dict[str, str] = {}
        for element in root.iter():
            namespace, local = self._split_tag(element.tag)
            prefix = self._namespace_prefix(namespace)
            identifier = f"xmp.{prefix}.{self._slug(local)}"
            labels[identifier] = local
            if element.text and element.text.strip():
                values[identifier].append(element.text.strip())
            for attribute, value in element.attrib.items():
                if not value or not str(value).strip():
                    continue
                attribute_namespace, attribute_local = self._split_tag(attribute)
                attribute_prefix = self._namespace_prefix(attribute_namespace)
                attribute_identifier = f"xmp.{attribute_prefix}.{self._slug(attribute_local)}"
                labels[attribute_identifier] = attribute_local
                values[attribute_identifier].append(str(value).strip())
        fields: list[MetadataField] = []
        for index, (identifier, raw_values) in enumerate(sorted(values.items()), start=1):
            value = ", ".join(dict.fromkeys(raw_values))
            parsed = (
                self._parse_iso_datetime(value)
                if identifier.endswith(("createdate", "modifydate", "metadatadate", "datecreated"))
                else None
            )
            fields.append(
                self._field(
                    identifier,
                    MetadataCategory.XMP,
                    labels[identifier],
                    parsed if parsed is not None else value,
                    MetadataValueType.DATETIME if parsed is not None else MetadataValueType.TEXT,
                    700 + index * 10,
                )
            )
        return fields

    def _format_fields(self, image: Image.Image, path: Path) -> list[MetadataField]:
        info = image.info
        format_name = (image.format or "").casefold()
        fields: list[MetadataField] = []
        compression = info.get("compression")
        if compression:
            fields.append(
                self._field(
                    "image.compression",
                    MetadataCategory.GENERAL,
                    "Compression",
                    str(compression),
                    MetadataValueType.TEXT,
                    90,
                )
            )
        if format_name == "png":
            fields.extend(self._png_chunk_fields(path, 800 + len(fields)))
            if "srgb" in info:
                fields.append(
                    self._field(
                        "png.srgb", MetadataCategory.GENERAL, "sRGB", int(info["srgb"]), MetadataValueType.INTEGER, 850
                    )
                )
        elif format_name == "gif":
            for key, label in (
                ("version", "Version"),
                ("loop", "Boucle"),
                ("duration", "Durée image"),
                ("transparency", "Transparence"),
            ):
                if key in info:
                    value = info[key]
                    fields.append(self._typed_info_field(f"gif.{key}", label, value, 900 + len(fields)))
            if info.get("comment"):
                fields.append(
                    self._field(
                        "gif.comment",
                        MetadataCategory.GENERAL,
                        "Commentaire",
                        self._string(info["comment"]),
                        MetadataValueType.TEXT,
                        950,
                    )
                )
        elif format_name == "webp":
            for key in ("loop", "background", "duration"):
                if key in info:
                    fields.append(self._typed_info_field(f"webp.{key}", key.title(), info[key], 1_000 + len(fields)))
        elif format_name in {"tiff", "bmp"}:
            if compression:
                fields.append(
                    self._field(
                        f"{format_name}.compression",
                        MetadataCategory.GENERAL,
                        "Compression",
                        str(compression),
                        MetadataValueType.TEXT,
                        1_100,
                    )
                )
        return fields

    def _icc_fields(self, profile: object) -> list[MetadataField]:
        if not profile:
            return []
        raw = bytes(profile)
        return [
            self._field(
                "image.icc_profile.sha256",
                MetadataCategory.GENERAL,
                "Profil ICC SHA-256",
                hashlib.sha256(raw).hexdigest(),
                MetadataValueType.TEXT,
                1_200,
            ),
            self._field(
                "image.icc_profile.size",
                MetadataCategory.GENERAL,
                "Taille profil ICC",
                len(raw),
                MetadataValueType.INTEGER,
                1_210,
                "o",
            ),
        ]

    def _thumbnail_fields(self, image_exif: object, exif_ifd) -> list[MetadataField]:
        thumbnail = self._tag(exif_ifd, "JPEGInterchangeFormat")
        length = self._integer(self._tag(exif_ifd, "JPEGInterchangeFormatLength"))
        raw_thumbnail = self._jpeg_thumbnail(image_exif)
        if thumbnail is None and length is None and raw_thumbnail is None:
            return []
        fields = [
            self._field(
                "exif.thumbnail.present",
                MetadataCategory.FORENSIC,
                "Miniature EXIF présente",
                True,
                MetadataValueType.BOOLEAN,
                1_300,
            )
        ]
        if length is not None:
            fields.append(
                self._field(
                    "exif.thumbnail.size",
                    MetadataCategory.FORENSIC,
                    "Taille miniature EXIF",
                    length,
                    MetadataValueType.INTEGER,
                    1_310,
                    "o",
                )
            )
        if raw_thumbnail is not None:
            fields.extend(
                (
                    self._field(
                        "exif.thumbnail.sha256",
                        MetadataCategory.FORENSIC,
                        "Miniature EXIF SHA-256",
                        hashlib.sha256(raw_thumbnail).hexdigest(),
                        MetadataValueType.TEXT,
                        1_320,
                    ),
                    self._field(
                        "exif.thumbnail.size",
                        MetadataCategory.FORENSIC,
                        "Taille miniature EXIF",
                        len(raw_thumbnail),
                        MetadataValueType.INTEGER,
                        1_330,
                        "o",
                    ),
                )
            )
        return fields

    def _png_chunk_fields(self, path: Path, order: int) -> list[MetadataField]:
        """Conserve distinctement tEXt, zTXt et iTXt sans charger les pixels."""
        fields: list[MetadataField] = []
        try:
            with path.open("rb") as source:
                if source.read(8) != b"\x89PNG\r\n\x1a\n":
                    return []
                while True:
                    header = source.read(8)
                    if len(header) != 8:
                        return fields
                    length, kind = struct.unpack(">I4s", header)
                    if length > self._MAX_PNG_CHUNK_BYTES:
                        source.seek(length + 4, 1)
                        continue
                    payload = source.read(length)
                    source.read(4)
                    if len(payload) != length:
                        return fields
                    if kind in {b"tEXt", b"zTXt", b"iTXt"}:
                        key, value = self._png_text(kind, payload)
                        if key and value is not None:
                            fields.append(
                                self._field(
                                    f"png.{kind.decode().casefold()}.{self._slug(key)}",
                                    MetadataCategory.XMP,
                                    f"PNG {kind.decode()} {key}",
                                    value,
                                    MetadataValueType.TEXT,
                                    order + len(fields),
                                )
                            )
                    if kind == b"IEND":
                        return fields
        except (OSError, struct.error, UnicodeError, zlib.error):
            return fields

    @classmethod
    def _png_text(cls, kind: bytes, payload: bytes) -> tuple[str, str | None]:
        key, separator, remainder = payload.partition(b"\0")
        if not separator:
            return "", None
        if kind == b"tEXt":
            return key.decode("latin-1", errors="replace"), remainder.decode("latin-1", errors="replace")
        if kind == b"zTXt":
            if not remainder:
                return "", None
            return key.decode("latin-1", errors="replace"), cls._bounded_zlib_text(remainder[1:])
        if len(remainder) < 2:
            return "", None
        compressed, _method = remainder[:2]
        language, _separator, remainder = remainder[2:].partition(b"\0")
        _translated, _separator, text = remainder.partition(b"\0")
        del language
        if compressed:
            return key.decode("utf-8", errors="replace"), cls._bounded_zlib_text(text)
        return key.decode("utf-8", errors="replace"), text.decode("utf-8", errors="replace")

    @classmethod
    def _bounded_zlib_text(cls, value: bytes) -> str:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(value, cls._MAX_PNG_TEXT_BYTES + 1)
        if len(decoded) > cls._MAX_PNG_TEXT_BYTES or decoder.unconsumed_tail:
            return decoded[: cls._MAX_PNG_TEXT_BYTES].decode("utf-8", errors="replace")
        return decoded.decode("utf-8", errors="replace")

    @staticmethod
    def _jpeg_thumbnail(raw_exif: object) -> bytes | None:
        if not isinstance(raw_exif, bytes) or not raw_exif.startswith(b"Exif\0\0") or len(raw_exif) < 14:
            return None
        tiff = raw_exif[6:]
        byte_order = tiff[:2]
        endian = "<" if byte_order == b"II" else ">" if byte_order == b"MM" else ""
        if not endian:
            return None
        try:
            ifd_offset = struct.unpack_from(f"{endian}I", tiff, 4)[0]
            entries = struct.unpack_from(f"{endian}H", tiff, ifd_offset)[0]
            ifd1_offset = struct.unpack_from(f"{endian}I", tiff, ifd_offset + 2 + entries * 12)[0]
            if ifd1_offset == 0:
                return None
            count = struct.unpack_from(f"{endian}H", tiff, ifd1_offset)[0]
            values = {
                struct.unpack_from(f"{endian}H", tiff, ifd1_offset + 2 + index * 12)[0]: struct.unpack_from(
                    f"{endian}I", tiff, ifd1_offset + 2 + index * 12 + 8
                )[0]
                for index in range(count)
            }
            offset, length = values.get(0x0201), values.get(0x0202)
            if offset is None or length is None:
                return None
            thumbnail = tiff[offset : offset + length]
            return thumbnail if len(thumbnail) == length else None
        except (IndexError, struct.error):
            return None

    def _raw_field(self, prefix: str, tag: int, label: str, value: object, order: int) -> MetadataField:
        numeric = self._ratio(value)
        if isinstance(value, bool):
            return self._field(f"{prefix}.{tag}", MetadataCategory.EXIF, label, value, MetadataValueType.BOOLEAN, order)
        if isinstance(value, int):
            return self._field(f"{prefix}.{tag}", MetadataCategory.EXIF, label, value, MetadataValueType.INTEGER, order)
        if isinstance(value, float) or numeric is not None and not isinstance(value, (str, bytes, tuple, list)):
            return self._field(
                f"{prefix}.{tag}", MetadataCategory.EXIF, label, numeric, MetadataValueType.DECIMAL, order
            )
        if isinstance(value, bytes):
            return self._field(
                f"{prefix}.{tag}.sha256",
                MetadataCategory.EXIF,
                f"{label} SHA-256",
                hashlib.sha256(value).hexdigest(),
                MetadataValueType.TEXT,
                order,
            )
        return self._field(
            f"{prefix}.{tag}", MetadataCategory.EXIF, label, self._string(value), MetadataValueType.TEXT, order
        )

    @staticmethod
    def _field(
        identifier: str,
        category: MetadataCategory,
        label: str,
        value: object,
        value_type: MetadataValueType,
        order: int,
        unit: str | None = None,
    ) -> MetadataField:
        return MetadataField(
            identifier, category, label, value, value_type, unit, "pillow.image", MetadataConfidence.HIGH, order
        )

    def _typed_info_field(self, identifier: str, label: str, value: object, order: int) -> MetadataField:
        if isinstance(value, bool):
            return self._field(identifier, MetadataCategory.GENERAL, label, value, MetadataValueType.BOOLEAN, order)
        if isinstance(value, int):
            return self._field(identifier, MetadataCategory.GENERAL, label, value, MetadataValueType.INTEGER, order)
        if isinstance(value, float):
            return self._field(identifier, MetadataCategory.GENERAL, label, value, MetadataValueType.DECIMAL, order)
        return self._field(identifier, MetadataCategory.GENERAL, label, str(value), MetadataValueType.TEXT, order)

    @staticmethod
    def _exif_ifd(exif):
        try:
            return exif.get_ifd(ExifTags.IFD.Exif)
        except (AttributeError, KeyError, TypeError, ValueError):
            return {}

    @staticmethod
    def _tag(values, name: str):
        tag_id = next((tag for tag, label in ExifTags.TAGS.items() if label == name), None)
        return values.get(tag_id) if tag_id is not None and values else None

    @staticmethod
    def _ratio(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError, ZeroDivisionError):
            if isinstance(value, tuple) and len(value) == 2 and value[1]:
                return float(value[0]) / float(value[1])
        return None

    @staticmethod
    def _integer(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _decimal_coordinates(self, coordinate: object, reference: object) -> float | None:
        if not isinstance(coordinate, (tuple, list)) or len(coordinate) != 3:
            return None
        parts = [self._ratio(part) for part in coordinate]
        if any(part is None for part in parts):
            return None
        value = float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
        return -value if str(reference).upper() in {"S", "W"} else value

    @staticmethod
    def _gps_speed_kmh(speed: float | None, reference: object) -> float | None:
        if speed is None:
            return None
        return speed * {"K": 1.0, "M": 1.609344, "N": 1.852}.get(str(reference).upper(), 1.0)

    @staticmethod
    def _gps_datetime(date_value: object, time_value: object) -> datetime | None:
        if not date_value or not isinstance(time_value, (tuple, list)) or len(time_value) < 3:
            return None
        try:
            year, month, day = (int(part) for part in re.split(r"[:/-]", str(date_value).strip()))
            parts = [ImageMetadataExtractor._ratio(value) for value in time_value[:3]]
            if any(value is None for value in parts):
                return None
            hour, minute, second = (float(value) for value in parts)
            return datetime(year, month, day, int(hour), int(minute), int(second), int((second % 1) * 1_000_000), UTC)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_exif_datetime(value: object, offset: object) -> tuple[datetime | None, bool]:
        if not value:
            return None, False
        try:
            parsed = datetime.strptime(str(value).strip().split("\x00", 1)[0], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            return None, False
        timezone_value = ImageMetadataExtractor._parse_offset(offset)
        return parsed.replace(tzinfo=timezone_value or UTC), timezone_value is None

    @staticmethod
    def _parse_offset(value: object) -> timezone | None:
        if not value:
            return None
        match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", str(value).strip())
        if match is None:
            return None
        sign = 1 if match.group(1) == "+" else -1
        return timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3))))

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _parse_iptc_date(value: str) -> datetime | None:
        try:
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            return None

    @staticmethod
    def _bits_per_pixel(image: Image.Image) -> int:
        known = {"1": 1, "L": 8, "P": 8, "LA": 16, "RGB": 24, "RGBA": 32, "CMYK": 32, "I": 32, "F": 32, "I;16": 16}
        bits = image.info.get("bits")
        if bits:
            bands = max(len(image.getbands()), 1)
            return int(bits) * bands
        return known.get(image.mode, max(len(image.getbands()), 1) * 8)

    @staticmethod
    def _split_tag(tag: str) -> tuple[str, str]:
        if tag.startswith("{") and "}" in tag:
            namespace, local = tag[1:].split("}", 1)
            return namespace, local
        return "", tag

    @staticmethod
    def _namespace_prefix(namespace: str) -> str:
        known = {
            "http://purl.org/dc/elements/1.1/": "dc",
            "http://ns.adobe.com/xap/1.0/": "xmp",
            "http://ns.adobe.com/photoshop/1.0/": "photoshop",
            "http://ns.adobe.com/exif/1.0/": "exif",
            "http://ns.adobe.com/tiff/1.0/": "tiff",
            "http://ns.adobe.com/camera-raw-settings/1.0/": "crs",
            "http://ns.adobe.com/lightroom/1.0/": "lightroom",
        }
        return known.get(namespace, "custom")

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "value"

    @staticmethod
    def _string(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        if isinstance(value, (tuple, list)):
            return ", ".join(ImageMetadataExtractor._string(item) for item in value)
        return str(value)
