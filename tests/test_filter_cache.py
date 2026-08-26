"""Non-régressions des valeurs normalisées utilisées par les filtres Fichiers."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex

from models.file_table_model import FileTableModel
from ui.file_filter_proxy import FileFilterProxyModel


class _TextValue:
    def __init__(self, value: str) -> None:
        self.value = value
        self.conversions = 0

    def __str__(self) -> str:
        self.conversions += 1
        return self.value


class _Artifact:
    def matches(self, filter_id: str) -> bool:
        return filter_id == "image.gps"


class _ArtifactCache:
    def __init__(self) -> None:
        self.calls = 0

    def cached_for(self, _record):
        self.calls += 1
        return (_Artifact(),)


def _record(**overrides):
    record = {
        "file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5",
        "name": "photo.jpg",
        "category": "Images",
        "mime": "image/jpeg",
        "sha256": "a" * 64,
        "output": "C:/case/Images/photo.jpg",
        "source_path": "D:/recovered/photo.jpg",
        "size": 1024,
    }
    record.update(overrides)
    return record


def test_search_fields_are_normalized_once_when_records_are_loaded(qapp):
    values = {field: _TextValue(f"Needle-{field}") for field in FileFilterProxyModel.SEARCH_FIELDS}
    values["file_id"] = "f4eaa4d1-cf9b-4884-b05b-5c53750636f5"
    model = FileTableModel(records=(_record(**values),))
    initial_conversions = sum(value.conversions for value in values.values() if isinstance(value, _TextValue))
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_search_text("needle")
    assert proxy.rowCount() == 1
    proxy.set_search_text("name")
    assert proxy.rowCount() == 1

    assert sum(value.conversions for value in values.values() if isinstance(value, _TextValue)) == initial_conversions


def test_cached_search_fields_preserve_name_category_mime_hash_and_path_matches(qapp):
    record = _record(
        name="Épreuve.jpg",
        sha256="abc123" * 10,
        output="C:/Case/Documents/Épreuve.jpg",
        source_path="D:/PhotoRec/recup_001.jpg",
    )
    model = FileTableModel(records=(record,))
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)

    for query in ("éPREUVE", "images", "image/jpeg", "abc123", "documents", "photorec"):
        proxy.set_search_text(query)
        assert proxy.rowCount() == 1


def test_artifact_match_is_cached_until_its_file_cache_changes(qapp):
    cache = _ArtifactCache()
    record = _record()
    model = FileTableModel(records=(record,))
    proxy = FileFilterProxyModel(cache)
    proxy.setSourceModel(model)
    proxy.set_artifact_filter("image.gps")
    proxy.rowCount()
    initial_calls = cache.calls

    assert proxy.filterAcceptsRow(0, QModelIndex())
    assert proxy.filterAcceptsRow(0, QModelIndex())
    assert cache.calls == initial_calls

    proxy.refresh_artifact_rows((record["file_id"],))
    assert proxy.filterAcceptsRow(0, QModelIndex())
    assert cache.calls == initial_calls + 1


def test_size_sort_uses_the_cached_numeric_value(qapp):
    class _Size:
        def __init__(self, value: int) -> None:
            self.value = value
            self.conversions = 0

        def __int__(self) -> int:
            self.conversions += 1
            return self.value

    first = _Size(1024)
    second = _Size(512)
    records = (_record(size=first), _record(file_id="a4eaa4d1-cf9b-4884-b05b-5c53750636f5", size=second))
    model = FileTableModel(records=records)
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)
    initial_conversions = first.conversions + second.conversions

    proxy.sort(FileTableModel.SIZE_COLUMN)
    assert proxy.rowCount() == 2

    assert first.conversions + second.conversions == initial_conversions
