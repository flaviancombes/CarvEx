from __future__ import annotations

from core.duplicates import DuplicateIndex
from models.file_table_model import FileTableModel
from ui.file_filter_proxy import FileFilterProxyModel


def _records():
    return (
        {
            "file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5",
            "name": "first.jpg",
            "category": "Images",
            "size": 400,
            "sha256": "a" * 64,
        },
        {
            "file_id": "4f6294bb-d88d-42c6-bb16-51fbee36a673",
            "name": "second.jpg",
            "category": "Images",
            "size": 100,
            "sha256": "a" * 64,
        },
        {
            "file_id": "6e3d9190-c2d2-4dfc-a2e8-782157e28f95",
            "name": "unique.pdf",
            "category": "Documents",
            "size": 200,
            "sha256": "b" * 64,
        },
    )


def test_duplicate_column_and_filter_use_the_shared_index(qapp):
    records = _records()
    index = DuplicateIndex()
    index.build(records)
    model = FileTableModel(records, duplicate_index=index)
    proxy = FileFilterProxyModel(duplicate_index=index)
    proxy.setSourceModel(model)

    assert model.data(model.index(0, FileTableModel.DUPLICATE_COUNT_COLUMN)) == 2
    assert model.data(model.index(2, FileTableModel.DUPLICATE_COUNT_COLUMN)) == 1

    proxy.set_duplicates_only(True)
    assert proxy.rowCount() == 2
    assert {proxy.index(row, 3).data() for row in range(proxy.rowCount())} == {"first.jpg", "second.jpg"}


def test_duplicate_filter_composes_with_existing_category_filter(qapp):
    records = _records()
    index = DuplicateIndex()
    index.build(records)
    proxy = FileFilterProxyModel(duplicate_index=index)
    proxy.setSourceModel(FileTableModel(records, duplicate_index=index))
    proxy.set_duplicates_only(True)
    proxy.set_category("Documents")

    assert proxy.rowCount() == 0
