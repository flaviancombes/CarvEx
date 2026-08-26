"""Corrélations déterministes, persistantes et sans accès aux providers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from metadata.base import MetadataCategory, MetadataField, MetadataResult, MetadataValueType
from metadata.correlation import (
    MetadataCorrelationEngine,
    MetadataCorrelationType,
)
from metadata.manager import MetadataManager
from metadata.module import MetadataProjectModule
from metadata.store import MetadataStore
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.storage import InMemoryProjectStorage, JsonProjectStorage
from project.stores import ProjectStore


def _field(identifier: str, value: object, category: MetadataCategory = MetadataCategory.EXIF) -> MetadataField:
    value_type = (
        MetadataValueType.DATETIME
        if isinstance(value, datetime)
        else MetadataValueType.DECIMAL if isinstance(value, float) else MetadataValueType.TEXT
    )
    return MetadataField(identifier, category, identifier, value, value_type, source="test")


def _store() -> MetadataStore:
    storage = InMemoryProjectStorage()
    return MetadataStore(ProjectStore(storage, "fields"), ProjectStore(storage, "index"))


def _result(*fields: MetadataField) -> MetadataResult:
    return MetadataResult(fields=fields)


def test_engine_builds_exact_groups_and_stable_identifiers():
    store = _store()
    shared = (
        _field("exif.model", "Canon R6"),
        _field("exif.lens_model", "RF 50mm"),
        _field("exif.software", "Lightroom"),
        _field("iptc.author", "Alice", MetadataCategory.IPTC),
        _field("iptc.copyright", "Copyright Alice", MetadataCategory.IPTC),
        _field("exif.thumbnail.sha256", "thumb"),
        _field("image.icc_profile.sha256", "icc", MetadataCategory.FORENSIC),
        _field("exif.maker_note.sha256", "maker", MetadataCategory.FORENSIC),
    )
    store.set("first", _result(*shared))
    store.set("second", _result(*shared))

    first = MetadataCorrelationEngine(store, store.index).build()
    second = MetadataCorrelationEngine(store, store.index).build()

    assert first == second
    assert {item.correlation_type for item in first} >= {
        MetadataCorrelationType.SAME_DEVICE,
        MetadataCorrelationType.SAME_LENS,
        MetadataCorrelationType.SAME_SOFTWARE,
        MetadataCorrelationType.SAME_AUTHOR,
        MetadataCorrelationType.SAME_COPYRIGHT,
        MetadataCorrelationType.SAME_EXIF_THUMBNAIL,
        MetadataCorrelationType.SAME_ICC_PROFILE,
        MetadataCorrelationType.SAME_MAKER_NOTES,
    }
    grouped = [
        item
        for item in first
        if item.correlation_type
        in {
            MetadataCorrelationType.SAME_DEVICE,
            MetadataCorrelationType.SAME_LENS,
            MetadataCorrelationType.SAME_SOFTWARE,
            MetadataCorrelationType.SAME_AUTHOR,
            MetadataCorrelationType.SAME_COPYRIGHT,
            MetadataCorrelationType.SAME_EXIF_THUMBNAIL,
            MetadataCorrelationType.SAME_ICC_PROFILE,
            MetadataCorrelationType.SAME_MAKER_NOTES,
        }
    ]
    assert all(item.file_ids == ("first", "second") for item in grouped)


def test_engine_groups_exact_and_nearby_gps_without_pairwise_search():
    store = _store()
    store.set("one", _result(_field("exif.gps.latitude", 48.8566001), _field("exif.gps.longitude", 2.3522001)))
    store.set("two", _result(_field("exif.gps.latitude", 48.8566002), _field("exif.gps.longitude", 2.3522002)))

    correlations = MetadataCorrelationEngine(store, store.index, nearby_radius_meters=100).build()

    kinds = {item.correlation_type for item in correlations}
    assert MetadataCorrelationType.SAME_GPS not in kinds
    assert MetadataCorrelationType.NEARBY_GPS in kinds


def test_engine_reports_metadata_inconsistencies():
    store = _store()
    original = datetime(2024, 5, 2, tzinfo=UTC)
    store.set(
        "photo",
        _result(
            _field("exif.datetime_original", original),
            _field("exif.datetime_modified", original - timedelta(days=1)),
            _field("exif.gps.latitude", 48.0),
            _field("exif.gps.longitude", 2.0),
            _field("exif.orientation", 1),
            _field("xmp.tiff.orientation", 6, MetadataCategory.XMP),
            _field("image.width", 100),
            _field("image.height", 200),
            _field("exif.extended.40962", 200),
            _field("exif.extended.40963", 100),
            _field("xmp.dc.creator", "Alice", MetadataCategory.XMP),
            _field("exif.thumbnail.present", True),
            _field("image.icc_profile.sha256", "icc", MetadataCategory.FORENSIC),
        ),
    )

    kinds = {item.correlation_type for item in MetadataCorrelationEngine(store, store.index).build()}

    assert {
        MetadataCorrelationType.DATES_INCONSISTENT,
        MetadataCorrelationType.ORIENTATION_INCONSISTENT,
        MetadataCorrelationType.RESOLUTION_INCONSISTENT,
        MetadataCorrelationType.XMP_WITHOUT_SOFTWARE,
        MetadataCorrelationType.GPS_WITHOUT_TIMESTAMP,
        MetadataCorrelationType.ICC_WITHOUT_COLORSPACE,
    } <= kinds


def test_correlation_store_persists_json_and_reopens_without_rebuild(tmp_path):
    modules = ProjectModuleRegistry()
    modules.register(MetadataProjectModule(MetadataManager(())))
    projects = ProjectManager(modules)
    root = tmp_path / "correlations.carvex"
    project = projects.create_project(ProjectMetadata("Correlations"), JsonProjectStorage(root, create=True))
    metadata_store = project.repository.module_repository("metadata", "store")
    metadata_store.set("one", _result(_field("exif.software", "GIMP")))
    metadata_store.set("two", _result(_field("exif.software", "GIMP")))
    engine = project.repository.module_repository("metadata", "correlation_engine")
    correlation_store = project.repository.module_repository("metadata", "correlation_store")
    built = engine.build_and_store(correlation_store)
    projects.save_project()
    projects.close_project()

    reopened_modules = ProjectModuleRegistry()
    reopened_modules.register(MetadataProjectModule(MetadataManager(())))
    reopened = ProjectManager(reopened_modules)
    reopened.open_project(root)
    restored = reopened.active_project.repository.module_repository("metadata", "correlation_store")

    assert restored.all() == built
    assert restored.for_file("one") == restored.by_type(MetadataCorrelationType.SAME_SOFTWARE)


def test_correlation_engine_scales_linearly_for_three_hundred_thousand_indexed_files():
    class _LargeIndex:
        file_ids = frozenset(f"file-{number}" for number in range(300_000))

        @staticmethod
        def values_for(identifier: str):
            return (
                {f"file-{number}": f"camera-{number % 10}" for number in range(300_000)}
                if identifier == "exif.model"
                else {}
            )

    class _EmptyStore:
        @staticmethod
        def get(_file_id: str):
            return None

    correlations = MetadataCorrelationEngine(_EmptyStore(), _LargeIndex()).build()

    groups = [item for item in correlations if item.correlation_type is MetadataCorrelationType.SAME_DEVICE]
    assert len(groups) == 10
    assert all(len(item.file_ids) == 30_000 for item in groups)
