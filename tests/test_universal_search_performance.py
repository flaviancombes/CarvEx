"""Régressions structurelles de la recherche universelle des fichiers."""

from __future__ import annotations

import pytest
from PySide6.QtTest import QTest

from ui.file_table import FileTable
from utils import performance


def _records(count: int) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "file_id": f"00000000-0000-4000-8000-{row:012d}",
            "name": f"evidence-{row:06d}.jpg",
            "category": "Images" if row % 2 else "Documents",
            "mime": "image/jpeg",
            "sha256": f"{row:064x}",
            "output": f"C:/case/evidence-{row:06d}.jpg",
            "source_path": f"D:/photorec/evidence-{row:06d}.jpg",
        }
        for row in range(count)
    )


def _wait_for_search(qapp) -> None:
    QTest.qWait(FileTable.SEARCH_DEBOUNCE_MS + 50)
    qapp.processEvents()
    qapp.processEvents()


@pytest.mark.parametrize("count", (1_000, 10_000, 50_000, 100_000))
def test_universal_search_profiles_one_proxy_pass_without_display_role_reads(qapp, monkeypatch, caplog, count):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    table = FileTable()
    table.set_files(_records(count))

    table.search_field.setText("evidence-000")
    _wait_for_search(qapp)

    messages = [record.message for record in caplog.records if "[UniversalSearch] model_update" in record.message]
    assert messages
    assert f"source_rows_at_start={count}" in messages[-1]
    assert f"filter_calls={count}" in messages[-1]
    assert "model_reset_count=0" in messages[-1]
    assert "source_data_accesses=0" in messages[-1]


def test_universal_search_replacement_and_clear_keep_the_same_matching_semantics(qapp):
    table = FileTable()
    table.set_files(_records(100))

    table.search_field.setText("evidence-000001")
    _wait_for_search(qapp)
    assert table.visible_file_count == 1
    table.search_field.setText("evidence-000002")
    _wait_for_search(qapp)
    assert table.visible_file_count == 1
    assert table.record_for_index(table._proxy_model.index(0, 0))["name"] == "evidence-000002.jpg"
    table.search_field.clear()
    _wait_for_search(qapp)

    assert table.visible_file_count == 100


def test_universal_search_coalesces_rapid_replacements(qapp, monkeypatch, caplog):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    table = FileTable()
    table.set_files(_records(100))

    for text in ("e", "ev", "evi", "evid", "evide", "eviden", "evidence-000042"):
        table.search_field.setText(text)
    _wait_for_search(qapp)

    actions = [record.message for record in caplog.records if "[UniversalSearch] action" in record.message]
    assert len(actions) == 1
    assert "query='evidence-000042'" in actions[0]
    assert table.visible_file_count == 1
