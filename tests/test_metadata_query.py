"""Régressions des requêtes MetadataIndex : aucune extraction ni I/O."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from PySide6.QtCore import Qt

from metadata.base import MetadataCategory, MetadataField, MetadataResult, MetadataValueType
from metadata.index import MetadataIndex
from metadata.manager import MetadataManager
from metadata.module import MetadataProjectModule
from metadata.query import MetadataPredicate, MetadataQuery
from metadata.store import MetadataStore
from models.file_table_model import FileTableModel
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.storage import InMemoryProjectStorage, JsonProjectStorage
from project.stores import ProjectStore
from ui.file_filter_proxy import FileFilterProxyModel
from ui.metadata_filter_panel import MetadataFilterPanel


def _field(identifier: str, value: object, value_type: MetadataValueType = MetadataValueType.TEXT) -> MetadataField:
    category = MetadataCategory.EXIF if identifier.startswith("exif.") else MetadataCategory.PDF
    return MetadataField(identifier, category, identifier, value, value_type, source="test")


def test_metadata_index_answers_forensic_presence_absence_and_exact_queries_without_provider():
    index = MetadataIndex()
    index.add("photo", (_field("exif.gps.latitude", "48.8566"), _field("exif.model", "Canon")))
    index.add("pdf", (_field("pdf.signed", True, MetadataValueType.BOOLEAN),))
    index.add("empty", ())

    assert MetadataQuery((MetadataPredicate("exif.gps.latitude"),)).execute(index) == frozenset({"photo"})
    assert MetadataQuery((MetadataPredicate("exif.gps.latitude", present=False),)).execute(index) == frozenset(
        {"pdf", "empty"}
    )
    assert MetadataQuery((MetadataPredicate("exif.model", "canon"),)).execute(index) == frozenset({"photo"})
    assert MetadataQuery((MetadataPredicate("pdf.signed", True),)).execute(index) == frozenset({"pdf"})


@pytest.mark.parametrize(
    ("identifier", "category", "value"),
    (
        ("exif.gps.latitude", MetadataCategory.EXIF, "48.8566"),
        ("exif.model", MetadataCategory.EXIF, "Canon EOS R6"),
        ("pdf.signed", MetadataCategory.PDF, True),
        ("office.has_macros", MetadataCategory.OFFICE, True),
        ("audio.codec", MetadataCategory.AUDIO, "FLAC"),
        ("video.codec", MetadataCategory.VIDEO, "H264"),
        ("archive.encrypted", MetadataCategory.ARCHIVES, True),
        ("pe.max_entropy", MetadataCategory.EXECUTABLE, 7.92),
        ("elf.bitness", MetadataCategory.EXECUTABLE, "64 bits"),
    ),
)
def test_metadata_index_supports_all_forensic_filter_families(identifier, category, value):
    index = MetadataIndex()
    field = MetadataField(identifier, category, identifier, value, source="test")
    index.add("evidence", (field,))

    assert MetadataQuery((MetadataPredicate(identifier),)).execute(index) == frozenset({"evidence"})


def test_metadata_index_intersects_filters_and_full_text_without_disk_access():
    index = MetadataIndex()
    index.add("one", (_field("exif.model", "Canon"), _field("exif.gps.latitude", "48.8")))
    index.add("two", (_field("exif.model", "Canon"),))
    index.add("three", (_field("exif.model", "Nikon"), _field("exif.gps.latitude", "43.6")))

    query = MetadataQuery(
        (MetadataPredicate("exif.model", "canon"), MetadataPredicate("exif.gps.latitude")), "model canon"
    )

    assert query.execute(index) == frozenset({"one"})


def test_metadata_index_uses_typed_numeric_and_datetime_sort_keys():
    index = MetadataIndex()
    index.add("large", (_field("pdf.pages", 100, MetadataValueType.INTEGER),))
    index.add("small", (_field("pdf.pages", 2, MetadataValueType.INTEGER),))
    index.add("older", (_field("pdf.creation", datetime(2020, 1, 1, tzinfo=UTC), MetadataValueType.DATETIME),))
    index.add("newer", (_field("pdf.creation", datetime(2024, 1, 1, tzinfo=UTC), MetadataValueType.DATETIME),))

    assert sorted(("large", "small"), key=lambda file_id: index.sort_key(file_id, "pdf.pages")) == ["small", "large"]
    assert sorted(("newer", "older"), key=lambda file_id: index.sort_key(file_id, "pdf.creation")) == ["older", "newer"]


def test_metadata_store_rebuilds_legacy_snapshot_once_and_persists_structured_index():
    storage = InMemoryProjectStorage()
    fields_store = ProjectStore(storage, "metadata:fields")
    index_store = ProjectStore(storage, "metadata:index")
    fields_store.set("photo", (_field("exif.model", "Canon"),))
    index_store.set("index", {"category": {}, "source": {}, "value": {}})

    store = MetadataStore(fields_store, index_store)

    assert store.index.equals("exif.model", "canon") == frozenset({"photo"})
    assert store.index.has_structured_fields is True
    assert "identifier" in index_store.get("index")


def test_metadata_queries_are_identical_after_json_project_reopen(tmp_path):
    modules = ProjectModuleRegistry()
    modules.register(MetadataProjectModule(MetadataManager(())))
    projects = ProjectManager(modules)
    root = tmp_path / "metadata.carvex"
    project = projects.create_project(ProjectMetadata("Metadata"), JsonProjectStorage(root, create=True))
    store = project.repository.module_repository("metadata", "store")
    store.set("photo", MetadataResult(fields=(_field("exif.model", "Canon"),)))
    projects.save_project()
    projects.close_project()

    reopened_modules = ProjectModuleRegistry()
    reopened_modules.register(MetadataProjectModule(MetadataManager(())))
    reopened = ProjectManager(reopened_modules)
    reopened.open_project(root)
    restored = reopened.active_project.repository.module_repository("metadata", "store")

    assert MetadataQuery((MetadataPredicate("exif.model", "canon"),)).execute(restored.index) == frozenset({"photo"})


def test_metadata_proxy_combines_metadata_and_existing_category_filter(qapp):
    records = (
        {"file_id": "00000000-0000-4000-8000-000000000001", "name": "photo.jpg", "category": "Images"},
        {"file_id": "00000000-0000-4000-8000-000000000002", "name": "report.pdf", "category": "Documents"},
    )
    index = MetadataIndex()
    index.add(records[0]["file_id"], (_field("exif.gps.latitude", "48.8"),))
    index.add(records[1]["file_id"], ())
    model = FileTableModel(records)
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.set_metadata_index(index)
    proxy.set_metadata_query(MetadataQuery((MetadataPredicate("exif.gps.latitude"),)))
    proxy.set_category("Images")

    assert proxy.rowCount() == 1
    assert proxy.index(0, 3).data() == "photo.jpg"


def test_metadata_proxy_sorts_numeric_values_without_display_string_order(qapp):
    records = (
        {"file_id": "00000000-0000-4000-8000-000000000010", "name": "ten.pdf", "category": "Documents"},
        {"file_id": "00000000-0000-4000-8000-000000000020", "name": "two.pdf", "category": "Documents"},
    )
    index = MetadataIndex()
    index.add(records[0]["file_id"], (_field("pdf.pages", 10, MetadataValueType.INTEGER),))
    index.add(records[1]["file_id"], (_field("pdf.pages", 2, MetadataValueType.INTEGER),))
    model = FileTableModel(records)
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.set_metadata_index(index)
    proxy.set_metadata_sort_identifier("pdf.pages")
    proxy.sort(3, Qt.SortOrder.AscendingOrder)

    assert proxy.index(0, 3).data() == "two.pdf"


def test_metadata_filter_panel_exposes_only_populated_categories_and_builds_query(qtbot):
    index = MetadataIndex()
    index.add("photo", (_field("exif.model", "Canon"),))
    panel = MetadataFilterPanel()
    qtbot.addWidget(panel)
    queries: list[MetadataQuery] = []
    panel.query_changed.connect(queries.append)

    panel.set_index(index)
    panel.category.setCurrentIndex(panel.category.findData("exif"))
    panel.field.setCurrentIndex(panel.field.findData("exif.model"))
    panel.mode.setCurrentIndex(2)
    panel.value.setText("Canon")
    panel.add_button.click()

    assert panel.category.findData("audio") == -1
    assert queries[-1].execute(index) == frozenset({"photo"})


def test_metadata_index_handles_three_hundred_thousand_indexed_records_without_extraction():
    index = MetadataIndex()
    for number in range(300_000):
        index.add(f"file-{number}", ())

    assert len(index.file_ids) == 300_000
    assert index.missing_field("exif.gps.latitude") == index.file_ids
