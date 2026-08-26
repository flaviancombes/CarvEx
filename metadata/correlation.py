"""Corrélations forensiques déterministes dérivées des métadonnées persistées.

Le module ne connaît ni Qt, ni disque, ni providers.  Il ne manipule que les
champs déjà présents dans :class:`metadata.store.MetadataStore` et les index
persistés associés.  Une corrélation est donc une projection reproductible,
jamais une nouvelle donnée de preuve.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from metadata.base import MetadataCategory, MetadataField
from metadata.index import MetadataIndex
from project.stores import ProjectStore
from utils.performance import pipeline_stage


class MetadataCorrelationType(StrEnum):
    SAME_DEVICE = "same_device"
    SAME_LENS = "same_lens"
    SAME_SOFTWARE = "same_software"
    SAME_AUTHOR = "same_author"
    SAME_COPYRIGHT = "same_copyright"
    SAME_GPS = "same_gps"
    NEARBY_GPS = "nearby_gps"
    SAME_ORIGIN_DIRECTORY = "same_origin_directory"
    SAME_EXIF_THUMBNAIL = "same_exif_thumbnail"
    SAME_ICC_PROFILE = "same_icc_profile"
    SAME_MAKER_NOTES = "same_maker_notes"
    DATES_INCONSISTENT = "dates_inconsistent"
    TIMEZONES_INCONSISTENT = "timezones_inconsistent"
    ORIENTATION_INCONSISTENT = "orientation_inconsistent"
    RESOLUTION_INCONSISTENT = "resolution_inconsistent"
    XMP_WITHOUT_SOFTWARE = "xmp_without_software"
    GPS_WITHOUT_TIMESTAMP = "gps_without_timestamp"
    THUMBNAIL_WITHOUT_EXIF = "thumbnail_without_exif"
    ICC_WITHOUT_COLORSPACE = "icc_without_colorspace"


@dataclass(frozen=True, slots=True)
class MetadataCorrelation:
    """Un groupe ou une anomalie, identifié seulement par des références ``file_id``."""

    correlation_id: str
    correlation_type: MetadataCorrelationType
    file_ids: tuple[str, ...]
    key: str
    summary: str

    def __post_init__(self) -> None:
        normalized_ids = tuple(sorted(set(self.file_ids)))
        object.__setattr__(self, "file_ids", normalized_ids)
        if not self.correlation_id or not self.key or not normalized_ids:
            raise ValueError("Une corrélation doit avoir un identifiant, une clé et des fichiers.")


class MetadataCorrelationIndex:
    """Index secondaire persistant : accès direct par corrélation, type ou fichier."""

    VERSION = 1
    INDEX_KEY = "index"

    def __init__(
        self, correlations: Iterable[MetadataCorrelation] = (), snapshot: Mapping[str, object] | None = None
    ) -> None:
        self._by_id: dict[str, MetadataCorrelation] = {}
        self._by_type: dict[MetadataCorrelationType, set[str]] = defaultdict(set)
        self._by_file: dict[str, set[str]] = defaultdict(set)
        if snapshot is None:
            self.replace(correlations)
        else:
            self._load_snapshot(correlations, snapshot)

    def replace(self, correlations: Iterable[MetadataCorrelation]) -> None:
        self._by_id.clear()
        self._by_type.clear()
        self._by_file.clear()
        for correlation in correlations:
            if correlation.correlation_id in self._by_id:
                raise ValueError(f"Identifiant de corrélation dupliqué : {correlation.correlation_id}")
            self._by_id[correlation.correlation_id] = correlation
            self._by_type[correlation.correlation_type].add(correlation.correlation_id)
            for file_id in correlation.file_ids:
                self._by_file[file_id].add(correlation.correlation_id)

    def get(self, correlation_id: str) -> MetadataCorrelation | None:
        return self._by_id.get(correlation_id)

    def for_file(self, file_id: str) -> tuple[MetadataCorrelation, ...]:
        return tuple(self._by_id[item] for item in sorted(self._by_file.get(file_id, ())))

    def by_type(self, correlation_type: MetadataCorrelationType) -> tuple[MetadataCorrelation, ...]:
        return tuple(self._by_id[item] for item in sorted(self._by_type.get(correlation_type, ())))

    def all(self) -> tuple[MetadataCorrelation, ...]:
        return tuple(self._by_id[item] for item in sorted(self._by_id))

    def snapshot(self) -> dict[str, object]:
        return {
            "version": self.VERSION,
            "by_type": {kind.value: tuple(sorted(values)) for kind, values in self._by_type.items()},
            "by_file": {file_id: tuple(sorted(values)) for file_id, values in self._by_file.items()},
        }

    def _load_snapshot(self, correlations: Iterable[MetadataCorrelation], snapshot: Mapping[str, object]) -> None:
        if snapshot.get("version") != self.VERSION:
            raise ValueError("Index de corrélation de métadonnées incompatible.")
        self._by_id = {item.correlation_id: item for item in correlations}
        raw_by_type, raw_by_file = snapshot.get("by_type"), snapshot.get("by_file")
        if not isinstance(raw_by_type, Mapping) or not isinstance(raw_by_file, Mapping):
            raise ValueError("Index de corrélation de métadonnées invalide.")
        known_ids = set(self._by_id)
        try:
            self._by_type = defaultdict(
                set,
                {
                    MetadataCorrelationType(str(kind)): self._snapshot_ids(values, known_ids)
                    for kind, values in raw_by_type.items()
                },
            )
        except ValueError as error:
            raise ValueError("Index de corrélation de métadonnées invalide.") from error
        self._by_file = defaultdict(
            set,
            {str(file_id): self._snapshot_ids(values, known_ids) for file_id, values in raw_by_file.items()},
        )
        expected_ids = set().union(*self._by_type.values(), *self._by_file.values()) if self._by_id else set()
        if expected_ids != known_ids:
            raise ValueError("Index de corrélation de métadonnées incohérent.")

    @staticmethod
    def _snapshot_ids(raw: object, known_ids: set[str]) -> set[str]:
        if not isinstance(raw, (list, tuple)):
            raise ValueError("Références de corrélation invalides.")
        values = {str(value) for value in raw}
        if not values <= known_ids:
            raise ValueError("Référence de corrélation inconnue.")
        return values


class MetadataCorrelationStore:
    """Source persistante officielle de la projection de corrélation.

    Les corrélations primaires sont stockées individuellement; l'index est une
    projection reconstruisible et ne contient que leurs identifiants.
    """

    VERSION = 1
    VERSION_KEY = "version"
    INDEX_KEY = MetadataCorrelationIndex.INDEX_KEY

    def __init__(self, correlations_store: ProjectStore, index_store: ProjectStore) -> None:
        self._correlations_store = correlations_store
        self._index_store = index_store
        correlations = self._load_correlations()
        snapshot = index_store.get(self.INDEX_KEY)
        self._index = (
            MetadataCorrelationIndex(correlations, snapshot)
            if snapshot is not None
            else MetadataCorrelationIndex(correlations)
        )
        if correlations_store.get(self.VERSION_KEY) is None:
            correlations_store.set(self.VERSION_KEY, self.VERSION)
        elif correlations_store.get(self.VERSION_KEY) != self.VERSION:
            raise ValueError("Version de corrélation de métadonnées incompatible.")
        if index_store.get(self.INDEX_KEY) is None:
            index_store.set(self.INDEX_KEY, self._index.snapshot())

    @property
    def index(self) -> MetadataCorrelationIndex:
        return self._index

    def replace(self, correlations: Iterable[MetadataCorrelation]) -> None:
        with pipeline_stage("MetadataCorrelationStore.sort"):
            values = tuple(sorted(correlations, key=lambda item: item.correlation_id))
        with pipeline_stage("MetadataCorrelationIndex.replace"):
            replacement = MetadataCorrelationIndex(values)
        previous = set(self._correlations_store.keys()) - {self.VERSION_KEY}
        try:
            with pipeline_stage("MetadataCorrelationStore.persist"):
                for key in previous:
                    self._correlations_store.delete(key)
                for correlation in values:
                    self._correlations_store.set(correlation.correlation_id, correlation)
            with pipeline_stage("MetadataCorrelationIndex.snapshot"):
                self._index_store.set(self.INDEX_KEY, replacement.snapshot())
        except Exception:
            # Les écritures projet sont atomiques au flush; ne publie jamais un
            # index mémoire en avance sur le store lors d'une erreur locale.
            raise
        self._index = replacement

    def get(self, correlation_id: str) -> MetadataCorrelation | None:
        return self._index.get(correlation_id)

    def for_file(self, file_id: str) -> tuple[MetadataCorrelation, ...]:
        return self._index.for_file(file_id)

    def by_type(self, correlation_type: MetadataCorrelationType) -> tuple[MetadataCorrelation, ...]:
        return self._index.by_type(correlation_type)

    def all(self) -> tuple[MetadataCorrelation, ...]:
        return self._index.all()

    def _load_correlations(self) -> tuple[MetadataCorrelation, ...]:
        correlations: list[MetadataCorrelation] = []
        for key in self._correlations_store.keys():
            if key == self.VERSION_KEY:
                continue
            correlation = self._correlations_store.get(key)
            if not isinstance(correlation, MetadataCorrelation):
                raise ValueError("Corrélation de métadonnées persistée invalide.")
            correlations.append(correlation)
        return tuple(correlations)


class MetadataCorrelationEngine:
    """Construit des projections déterministes à partir du Store et de l'Index.

    Les regroupements exacts s'appuient sur les index de valeurs existants. Les
    coordonnées proches sont groupées dans une grille géographique dont la
    diagonale est inférieure au rayon demandé : aucune comparaison quadratique
    de toutes les coordonnées n'est donc requise.
    """

    _EXACT_GROUPS = (
        (
            MetadataCorrelationType.SAME_DEVICE,
            ("exif.extended.42033", "exif.extended.42016", "exif.model"),
            "Appareil identique",
        ),
        (MetadataCorrelationType.SAME_LENS, ("exif.lens_model",), "Objectif identique"),
        (MetadataCorrelationType.SAME_SOFTWARE, ("exif.software", "xmp.xmp.creatortool"), "Logiciel identique"),
        (MetadataCorrelationType.SAME_AUTHOR, ("iptc.author", "xmp.dc.creator", "exif.artist"), "Auteur identique"),
        (
            MetadataCorrelationType.SAME_COPYRIGHT,
            ("iptc.copyright", "xmp.dc.rights", "exif.copyright"),
            "Copyright identique",
        ),
        (
            MetadataCorrelationType.SAME_ORIGIN_DIRECTORY,
            ("filesystem.origin_directory",),
            "Dossier d'origine identique",
        ),
        (MetadataCorrelationType.SAME_EXIF_THUMBNAIL, ("exif.thumbnail.sha256",), "Miniature EXIF identique"),
        (MetadataCorrelationType.SAME_ICC_PROFILE, ("image.icc_profile.sha256",), "Profil ICC identique"),
        (MetadataCorrelationType.SAME_MAKER_NOTES, ("exif.maker_note.sha256",), "MakerNotes identiques"),
    )

    def __init__(self, metadata_store, metadata_index: MetadataIndex, nearby_radius_meters: float = 50.0) -> None:
        if nearby_radius_meters <= 0:
            raise ValueError("Le rayon GPS doit être strictement positif.")
        self._store = metadata_store
        self._index = metadata_index
        self._nearby_radius_meters = float(nearby_radius_meters)

    def build(self) -> tuple[MetadataCorrelation, ...]:
        correlations: list[MetadataCorrelation] = []
        for correlation_type, identifiers, title in self._EXACT_GROUPS:
            with pipeline_stage(f"CorrelationEngine.exact_groups.{correlation_type.value}"):
                correlations.extend(self._exact_groups(correlation_type, identifiers, title))
        with pipeline_stage("CorrelationEngine.gps_groups"):
            correlations.extend(self._gps_groups())
        with pipeline_stage("CorrelationEngine.nearby_gps_groups"):
            correlations.extend(self._nearby_gps_groups())
        with pipeline_stage("CorrelationEngine.anomalies"):
            correlations.extend(self._anomalies())
        return tuple(sorted(correlations, key=lambda item: item.correlation_id))

    def build_and_store(self, correlation_store: MetadataCorrelationStore) -> tuple[MetadataCorrelation, ...]:
        with pipeline_stage("CorrelationEngine.build"):
            correlations = self.build()
        with pipeline_stage("MetadataCorrelationStore.replace"):
            correlation_store.replace(correlations)
        return correlations

    def _exact_groups(
        self, correlation_type: MetadataCorrelationType, identifiers: tuple[str, ...], title: str
    ) -> list[MetadataCorrelation]:
        groups: dict[str, set[str]] = defaultdict(set)
        for identifier in identifiers:
            for file_id, value in self._index.values_for(identifier).items():
                normalized = self._normalize(value)
                if normalized:
                    groups[normalized].add(file_id)
        return [
            self._group(correlation_type, key, ids, f"{title} : {key}")
            for key, ids in sorted(groups.items())
            if len(ids) > 1
        ]

    def _gps_groups(self) -> list[MetadataCorrelation]:
        latitudes = self._index.values_for("exif.gps.latitude")
        longitudes = self._index.values_for("exif.gps.longitude")
        groups: dict[str, set[str]] = defaultdict(set)
        for file_id in set(latitudes).intersection(longitudes):
            latitude, longitude = self._coordinate(latitudes[file_id]), self._coordinate(longitudes[file_id])
            if latitude is not None and longitude is not None:
                groups[f"{latitude:.7f},{longitude:.7f}"].add(file_id)
        return [
            self._group(MetadataCorrelationType.SAME_GPS, key, ids, f"Coordonnées GPS identiques : {key}")
            for key, ids in sorted(groups.items())
            if len(ids) > 1
        ]

    def _nearby_gps_groups(self) -> list[MetadataCorrelation]:
        latitudes = self._index.values_for("exif.gps.latitude")
        longitudes = self._index.values_for("exif.gps.longitude")
        cell_size = self._nearby_radius_meters / 160_000.0
        groups: dict[tuple[int, int], set[str]] = defaultdict(set)
        for file_id in set(latitudes).intersection(longitudes):
            latitude, longitude = self._coordinate(latitudes[file_id]), self._coordinate(longitudes[file_id])
            if latitude is not None and longitude is not None:
                groups[(math.floor(latitude / cell_size), math.floor(longitude / cell_size))].add(file_id)
        return [
            self._group(
                MetadataCorrelationType.NEARBY_GPS,
                f"{cell[0]}:{cell[1]}:{self._nearby_radius_meters:g}",
                ids,
                f"Coordonnées GPS proches (≤ {self._nearby_radius_meters:g} m)",
            )
            for cell, ids in sorted(groups.items())
            if len(ids) > 1
        ]

    def _anomalies(self) -> list[MetadataCorrelation]:
        correlations: list[MetadataCorrelation] = []
        for file_id in sorted(self._index.file_ids):
            fields = self._store.get(file_id)
            if fields is None:
                continue
            by_id = {field.identifier.casefold(): field for field in fields.fields}
            present = set(by_id)
            correlations.extend(self._date_anomalies(file_id, by_id))
            orientation = self._value(by_id, "exif.orientation")
            xmp_orientation = self._value(by_id, "xmp.tiff.orientation")
            if orientation is not None and xmp_orientation is not None and str(orientation) != str(xmp_orientation):
                correlations.append(
                    self._anomaly(
                        MetadataCorrelationType.ORIENTATION_INCONSISTENT, file_id, "Orientation EXIF/XMP incohérente"
                    )
                )
            width, height = self._value(by_id, "image.width"), self._value(by_id, "image.height")
            xmp_width, xmp_height = self._value(by_id, "exif.extended.40962"), self._value(by_id, "exif.extended.40963")
            if (
                width is not None
                and height is not None
                and xmp_width is not None
                and xmp_height is not None
                and (str(width), str(height)) != (str(xmp_width), str(xmp_height))
            ):
                correlations.append(
                    self._anomaly(
                        MetadataCorrelationType.RESOLUTION_INCONSISTENT, file_id, "Résolution image/EXIF incohérente"
                    )
                )
            has_xmp = any(field.category is MetadataCategory.XMP for field in fields.fields)
            if has_xmp and not any(key in present for key in ("exif.software", "xmp.xmp.creatortool")):
                correlations.append(
                    self._anomaly(
                        MetadataCorrelationType.XMP_WITHOUT_SOFTWARE, file_id, "XMP présent sans logiciel déclaré"
                    )
                )
            has_gps = {"exif.gps.latitude", "exif.gps.longitude"} <= present
            if has_gps and "exif.gps.timestamp" not in present:
                correlations.append(
                    self._anomaly(MetadataCorrelationType.GPS_WITHOUT_TIMESTAMP, file_id, "GPS présent sans date GPS")
                )
            has_thumbnail = bool(self._value(by_id, "exif.thumbnail.present"))
            has_exif = any(
                field.category is MetadataCategory.EXIF and not field.identifier.startswith("exif.thumbnail")
                for field in fields.fields
            )
            if has_thumbnail and not has_exif:
                correlations.append(
                    self._anomaly(
                        MetadataCorrelationType.THUMBNAIL_WITHOUT_EXIF, file_id, "Miniature présente sans EXIF"
                    )
                )
            has_icc = any(field.identifier.startswith("image.icc_profile") for field in fields.fields)
            if has_icc and "exif.color_space" not in present:
                correlations.append(
                    self._anomaly(
                        MetadataCorrelationType.ICC_WITHOUT_COLORSPACE,
                        file_id,
                        "Profil ICC présent sans ColorSpace déclaré",
                    )
                )
        return correlations

    def _date_anomalies(self, file_id: str, fields: Mapping[str, MetadataField]) -> list[MetadataCorrelation]:
        original, modified = self._value(fields, "exif.datetime_original"), self._value(
            fields, "exif.datetime_modified"
        )
        result: list[MetadataCorrelation] = []
        if isinstance(original, datetime) and isinstance(modified, datetime) and modified < original:
            result.append(
                self._anomaly(
                    MetadataCorrelationType.DATES_INCONSISTENT,
                    file_id,
                    "Date de modification antérieure à la prise de vue",
                )
            )
        offsets = {
            value.utcoffset()
            for value in (
                self._value(fields, "exif.datetime_original"),
                self._value(fields, "exif.datetime_modified"),
                self._value(fields, "exif.gps.timestamp"),
            )
            if isinstance(value, datetime) and value.tzinfo is not None
        }
        if len(offsets) > 1:
            result.append(
                self._anomaly(
                    MetadataCorrelationType.TIMEZONES_INCONSISTENT, file_id, "Fuseaux horaires des dates incohérents"
                )
            )
        return result

    @staticmethod
    def _value(fields: Mapping[str, MetadataField], identifier: str) -> object | None:
        field = fields.get(identifier)
        return None if field is None else field.value

    @staticmethod
    def _coordinate(value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if -180.0 <= result <= 180.0 else None

    @staticmethod
    def _normalize(value: object) -> str:
        return str(value).strip().casefold()

    @classmethod
    def _group(
        cls, correlation_type: MetadataCorrelationType, key: str, file_ids: Iterable[str], summary: str
    ) -> MetadataCorrelation:
        normalized_ids = tuple(sorted(set(file_ids)))
        return MetadataCorrelation(
            cls._identifier(correlation_type, key, normalized_ids), correlation_type, normalized_ids, key, summary
        )

    @classmethod
    def _anomaly(cls, correlation_type: MetadataCorrelationType, file_id: str, summary: str) -> MetadataCorrelation:
        return cls._group(correlation_type, file_id, (file_id,), summary)

    @staticmethod
    def _identifier(correlation_type: MetadataCorrelationType, key: str, file_ids: tuple[str, ...]) -> str:
        payload = json.dumps(
            {"type": correlation_type.value, "key": key, "file_ids": file_ids},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
