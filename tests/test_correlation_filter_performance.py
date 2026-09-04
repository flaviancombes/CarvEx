"""Régressions structurelles des filtres Corrélations déjà indexés."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from metadata.correlation import MetadataCorrelation, MetadataCorrelationIndex, MetadataCorrelationType
from ui.file_table import FileTable
from utils import performance


def _records(count: int) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "file_id": f"00000000-0000-4000-8000-{row:012d}",
            "name": f"file-{row:06d}.jpg",
            "category": "Images",
        }
        for row in range(count)
    )


def _index(records: tuple[dict[str, str], ...]) -> MetadataCorrelationIndex:
    return MetadataCorrelationIndex(
        (
            MetadataCorrelation(
                "same-device-canon",
                MetadataCorrelationType.SAME_DEVICE,
                tuple(record["file_id"] for record in records[::2]),
                "Canon",
                "Même appareil : Canon",
            ),
        )
    )


def test_correlation_filter_uses_its_cached_projection_without_index_rebuild(qapp):
    records = _records(1_000)
    table = FileTable()
    table.set_files(records)
    table.set_correlation_index(_index(records))

    class NoReadIndex:
        def all(self):
            raise AssertionError("un changement de filtre ne doit pas relire l'index")

    table.correlation_filters._index = NoReadIndex()
    table.correlation_filters.correlated_only.setChecked(True)

    assert table.visible_file_count == 500


def test_correlation_filter_profiles_one_proxy_pass_without_model_reset(qapp, monkeypatch, caplog):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    records = _records(1_000)
    table = FileTable()
    table.set_files(records)
    table.set_correlation_index(_index(records))
    table.correlation_filters.correlated_only.setChecked(True)
    qapp.processEvents()
    qapp.processEvents()

    message = "\n".join(record.message for record in caplog.records)
    assert "[CorrelationsFilter] resolve_state" in message
    assert "[CorrelationsFilter] model_update" in message
    assert "source_rows_at_start=1000" in message
    assert "filter_calls=1000" in message
    assert "model_reset=0" in message


def test_correlation_filter_composes_type_and_text_without_rebuilding_index(qapp):
    records = _records(1_000)
    table = FileTable()
    table.set_files(records)
    table.set_correlation_index(_index(records))
    check = next(iter(table.correlation_filters._type_checks.values()))

    check.setChecked(True)
    assert table.visible_file_count == 500
    table.correlation_filters.search.setText("Canon")
    assert table.visible_file_count == 500
    table.correlation_filters.search.clear()
    check.setChecked(False)
    assert table.visible_file_count == 1_000


@pytest.mark.parametrize("count", (1_000, 10_000, 50_000))
def test_correlation_filter_performs_one_source_pass_at_each_supported_scale(qapp, monkeypatch, caplog, count):
    """Le coût doit rester une passe proxy, jamais un rebuild de corrélations."""
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    records = _records(count)
    table = FileTable()
    table.set_files(records)
    table.set_correlation_index(_index(records))
    table.correlation_filters.correlated_only.setChecked(True)
    qapp.processEvents()
    qapp.processEvents()

    messages = [record.message for record in caplog.records if "[CorrelationsFilter] model_update" in record.message]
    assert messages
    assert f"source_rows_at_start={count}" in messages[-1]
    assert f"filter_calls={count}" in messages[-1]
    assert "model_reset=0" in messages[-1]


def test_correlation_filter_profiles_the_existing_sorted_projection(qapp, monkeypatch, caplog):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    records = _records(10_000)
    table = FileTable()
    table.set_files(records)
    table.set_correlation_index(_index(records))
    table._proxy_model.sort(3, Qt.SortOrder.AscendingOrder)
    table.correlation_filters.correlated_only.setChecked(True)
    qapp.processEvents()
    qapp.processEvents()

    messages = [record.message for record in caplog.records if "[CorrelationsFilter] model_update" in record.message]
    assert messages
    assert "filter_calls=10000" in messages[-1]
    assert "model_reset=0" in messages[-1]
