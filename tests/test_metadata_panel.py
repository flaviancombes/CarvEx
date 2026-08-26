"""Tests du panneau Qt de métadonnées sans extraction pendant le rendu."""

from __future__ import annotations

from uuid import uuid4

from PySide6.QtWidgets import QApplication

from metadata.base import MetadataCategory, MetadataField, MetadataResult
from metadata.cache import MetadataCache
from metadata.manager import MetadataManager
from metadata.store import MetadataStore
from project.storage import InMemoryProjectStorage
from project.stores import ProjectStore
from ui.metadata_panel import MetadataPanel


def _record():
    return {"file_id": str(uuid4()), "name": "evidence.jpg"}


def _field(identifier: str, category: MetadataCategory, value: str | int, order: int = 0) -> MetadataField:
    return MetadataField(identifier, category, identifier, value, source="test", display_order=order)


def test_panel_groups_categories_hides_empty_and_uses_cache_only(qtbot):
    cache = MetadataCache()
    record = _record()
    cache.set(
        record,
        MetadataResult(
            fields=(
                _field("exif.model", MetadataCategory.EXIF, "R6"),
                _field("general.name", MetadataCategory.GENERAL, "Photo"),
            )
        ),
    )
    panel = MetadataPanel(cache)
    qtbot.addWidget(panel)

    panel.set_file(record)

    assert panel.tree.isVisible() is False  # Le parent non affiché rend le widget non visible sous Qt.
    assert panel.model.rowCount() == 2
    assert [panel.model.index(row, 0).data() for row in range(2)] == ["General", "Exif"]


def test_panel_search_copy_and_formatting(qtbot):
    cache = MetadataCache()
    record = _record()
    cache.set(
        record,
        MetadataResult(
            fields=(
                _field("archive.compressed_size", MetadataCategory.ARCHIVES, 1795),
                _field("exif.datetime_original", MetadataCategory.EXIF, "2025:03:15 14:18:22"),
            )
        ),
    )
    panel = MetadataPanel(cache)
    qtbot.addWidget(panel)
    panel.show()
    panel.set_file(record)
    panel.search.setText("compressed")
    category = panel.model.index(0, 0)
    value = panel.model.index(0, 1, category)
    panel.tree.setCurrentIndex(value)

    assert value.data() == "1,75 KiB"
    panel.copy_cell()
    assert qtbot.waitUntil(lambda: panel.tree.currentIndex().isValid()) is None
    assert QApplication.clipboard().text() == "1,75 KiB"
    assert panel.model.line_text(value).split("\t")[1] == "1,75 KiB"
    panel.copy_category()
    assert "archive.compressed_size" in QApplication.clipboard().text()
    panel.search.setText("datetime")
    date = panel.model.index(0, 1, panel.model.index(0, 0))
    assert date.data() == "2025-03-15T14:18:22"


def test_large_metadata_set_filters_without_reextracting(qtbot):
    cache = MetadataCache()
    record = _record()
    fields = tuple(
        _field(f"xmp.field_{index}", MetadataCategory.XMP, f"value {index}", index) for index in range(5_000)
    )
    cache.set(record, MetadataResult(fields=fields))
    panel = MetadataPanel(cache)
    qtbot.addWidget(panel)

    panel.set_file(record)
    panel.search.setText("field_4999")

    assert panel.model.rowCount() == 1
    assert panel.model.rowCount(panel.model.index(0, 0)) == 1


def test_panel_hydrates_persisted_metadata_without_provider_extraction(qtbot):
    record = _record()
    cache = MetadataCache()
    manager = MetadataManager((), cache)
    store = MetadataStore(
        ProjectStore(InMemoryProjectStorage(), "fields"), ProjectStore(InMemoryProjectStorage(), "index")
    )
    manager.attach_store(store)
    store.set(record["file_id"], MetadataResult(fields=(_field("exif.model", MetadataCategory.EXIF, "R6"),)))
    panel = MetadataPanel(cache, manager=manager)
    qtbot.addWidget(panel)

    panel.set_file(record)

    assert panel.model.rowCount() == 1
    assert cache.get(record) is not None
