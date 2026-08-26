from __future__ import annotations

from PySide6.QtCore import QModelIndex

from models.file_table_model import FileTableModel
from ui.file_filter_proxy import FileFilterProxyModel


class CacheOnlyArtifacts:
    def __init__(self) -> None:
        self.calls = 0

    def cached_for(self, _record):
        self.calls += 1
        return None


def test_artifact_filter_only_reads_the_cache_and_never_calculates(qapp):
    cache = CacheOnlyArtifacts()
    model = FileTableModel(
        records=({"file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5", "name": "photo.jpg", "category": "Images"},)
    )
    proxy = FileFilterProxyModel(artifact_cache=cache)
    proxy.setSourceModel(model)
    proxy.set_artifact_filter("image.gps")

    assert not proxy.filterAcceptsRow(0, QModelIndex())
    assert cache.calls == 1


def test_missing_artifact_cache_entry_excludes_row_without_metadata_work(qapp):
    class EmptyCache:
        def cached_for(self, _record):
            return None

    model = FileTableModel(
        records=({"file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5", "name": "photo.jpg", "category": "Images"},)
    )
    proxy = FileFilterProxyModel(artifact_cache=EmptyCache())
    proxy.setSourceModel(model)
    proxy.set_artifact_filter("image.exif")

    assert proxy.rowCount() == 0
