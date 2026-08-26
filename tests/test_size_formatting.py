"""Rendu IEC des tailles sans modifier les valeurs utilisées par le tri."""

from __future__ import annotations

from models.file_table_model import FileTableModel
from ui.file_filter_proxy import FileFilterProxyModel
from utils.performance import format_byte_size


def test_format_byte_size_uses_iec_units():
    assert format_byte_size(512) == "512 o"
    assert format_byte_size(1024) == "1,00 KiB"
    assert format_byte_size(1795) == "1,75 KiB"
    assert format_byte_size(1024**2) == "1,00 MiB"
    assert format_byte_size(1024**3) == "1,00 GiB"


def test_file_size_display_and_sort_keep_the_raw_byte_order(qapp):
    records = (
        {"file_id": "c0a3aa11-0cf1-4d0a-bd5b-1e726f0f12e1", "name": "large", "size": 1795},
        {"file_id": "a1a3aa11-0cf1-4d0a-bd5b-1e726f0f12e1", "name": "small", "size": 512},
        {"file_id": "b2a3aa11-0cf1-4d0a-bd5b-1e726f0f12e1", "name": "medium", "size": 1024},
    )
    model = FileTableModel(records=records)
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.sort(FileTableModel.SIZE_COLUMN)

    assert model.data(model.index(0, FileTableModel.SIZE_COLUMN)) == "1,75 KiB"
    assert [proxy.index(row, 3).data() for row in range(proxy.rowCount())] == ["small", "medium", "large"]
