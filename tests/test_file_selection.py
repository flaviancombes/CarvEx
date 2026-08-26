"""Canonical bulk selection remains independent from sorting and filtering widgets."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtCore import QItemSelectionModel, Qt

from selection.file_selection import FileSelectionModel
from timeline.event import TimelineEvent
from timeline.model import TimelineTableModel
from timeline.source import FILE_MODIFIED, FILESYSTEM
from ui.file_table import FileTable


def _records(count: int = 4):
    return tuple(
        {
            "file_id": str(uuid4()),
            "name": f"file-{index}.jpg",
            "category": "Images" if index % 2 else "Documents",
            "mime": "image/jpeg",
        }
        for index in range(count)
    )


def test_selection_model_uses_only_canonical_ids_and_notifies_incrementally():
    selection = FileSelectionModel()
    changes = []
    selection.changed.connect(changes.append)

    selection.select_many(("file-a", "file-b", "file-a"))
    selection.deselect_many(("file-a", "missing"))

    assert selection.selected_ids() == frozenset({"file-b"})
    assert changes[0].added == ("file-a", "file-b")
    assert changes[1].removed == ("file-a",)


def test_file_checkboxes_survive_filter_changes_and_only_depend_on_file_ids(qtbot):
    selection = FileSelectionModel()
    table = FileTable(file_selection=selection)
    qtbot.addWidget(table)
    records = _records()
    table.set_files(records)

    selection.select_many((str(records[0]["file_id"]), str(records[1]["file_id"])))
    table._proxy_model.set_category("Images")

    assert selection.count == 2
    source_index = table._source_model.index(1, table._source_model.SELECTION_COLUMN)
    assert table._source_model.data(source_index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked


def test_header_selects_and_deselects_only_visible_files_without_resetting_the_model(qtbot):
    selection = FileSelectionModel()
    table = FileTable(file_selection=selection)
    qtbot.addWidget(table)
    records = _records(200)
    table.set_files(records)
    resets = []
    table._source_model.modelReset.connect(lambda: resets.append(True))

    table._toggle_header_selection(table._source_model.SELECTION_COLUMN)
    assert selection.count == 200
    table._toggle_header_selection(table._source_model.SELECTION_COLUMN)

    assert selection.count == 0
    assert not resets


def test_bulk_investigation_marker_refresh_is_bounded_and_never_resets(qtbot):
    table = FileTable(file_selection=FileSelectionModel())
    qtbot.addWidget(table)
    records = _records(1_000)
    table.set_files(records)
    resets = []
    changes = []
    table._source_model.modelReset.connect(lambda: resets.append(True))
    table._source_model.dataChanged.connect(lambda *_args: changes.append(True))

    table.refresh_investigation_markers(str(record["file_id"]) for record in records)

    assert not resets
    assert len(changes) == 1


def test_qt_row_selection_does_not_change_checkbox_selection(qtbot):
    selection = FileSelectionModel()
    table = FileTable(file_selection=selection)
    qtbot.addWidget(table)
    records = _records(3)
    table.set_files(records)

    table.view.selectionModel().select(
        table._proxy_model.index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
    )

    assert table.view.selectionModel().isSelected(table._proxy_model.index(0, 0))
    assert selection.count == 0


def test_checkbox_selection_accepts_an_arbitrary_subset_and_individual_removal(qtbot):
    selection = FileSelectionModel()
    table = FileTable(file_selection=selection)
    qtbot.addWidget(table)
    records = _records(10)
    table.set_files(records)

    for row in (0, 3, 4, 8):
        assert table._proxy_model.setData(
            table._proxy_model.index(row, table._source_model.SELECTION_COLUMN),
            Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )
    assert selection.selected_ids() == {str(records[row]["file_id"]) for row in (0, 3, 4, 8)}

    assert table._proxy_model.setData(
        table._proxy_model.index(3, table._source_model.SELECTION_COLUMN),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert selection.selected_ids() == {str(records[row]["file_id"]) for row in (0, 4, 8)}


def test_individual_checkbox_clicks_toggle_only_the_clicked_file_without_reset(qtbot):
    selection = FileSelectionModel()
    table = FileTable(file_selection=selection)
    qtbot.addWidget(table)
    records = _records(10)
    table.set_files(records)
    table.resize(1_000, 600)
    table.show()
    resets = []
    table._source_model.modelReset.connect(lambda: resets.append(True))

    for row in (2, 7, 9):
        index = table._proxy_model.index(row, table._source_model.SELECTION_COLUMN)
        qtbot.mouseClick(table.view.viewport(), Qt.MouseButton.LeftButton, pos=table.view.visualRect(index).center())

    assert selection.selected_ids() == {str(records[row]["file_id"]) for row in (2, 7, 9)}

    index = table._proxy_model.index(7, table._source_model.SELECTION_COLUMN)
    qtbot.mouseClick(table.view.viewport(), Qt.MouseButton.LeftButton, pos=table.view.visualRect(index).center())

    assert selection.selected_ids() == {str(records[row]["file_id"]) for row in (2, 9)}
    assert not resets


def test_checkbox_clicks_are_immediately_reflected_by_the_timeline_model(qtbot):
    selection = FileSelectionModel()
    table = FileTable(file_selection=selection)
    qtbot.addWidget(table)
    records = _records(3)
    table.set_files(records)
    table.resize(1_000, 600)
    table.show()
    timeline = TimelineTableModel(file_selection=selection)
    timeline.set_events(
        tuple(
            TimelineEvent(FILE_MODIFIED, datetime(2025, 3, 20, tzinfo=UTC), FILESYSTEM, file_record=record)
            for record in records
        )
    )

    index = table._proxy_model.index(1, table._source_model.SELECTION_COLUMN)
    qtbot.mouseClick(table.view.viewport(), Qt.MouseButton.LeftButton, pos=table.view.visualRect(index).center())

    assert selection.selected_ids() == {str(records[1]["file_id"])}
    selected_states = {
        timeline.file_id_for_index(timeline.index(row, timeline.SELECTION_COLUMN)): timeline.data(
            timeline.index(row, timeline.SELECTION_COLUMN), Qt.ItemDataRole.CheckStateRole
        )
        for row in range(timeline.rowCount())
    }
    assert selected_states[str(records[1]["file_id"])] == Qt.CheckState.Checked
    assert selected_states[str(records[0]["file_id"])] == Qt.CheckState.Unchecked


def test_checkbox_selection_survives_sort_filter_and_search(qtbot):
    selection = FileSelectionModel()
    table = FileTable(file_selection=selection)
    qtbot.addWidget(table)
    records = _records(6)
    table.set_files(records)
    expected_ids = (str(records[0]["file_id"]), str(records[3]["file_id"]), str(records[5]["file_id"]))
    selection.select_many(expected_ids)

    table._proxy_model.sort(3, Qt.SortOrder.DescendingOrder)
    table._proxy_model.set_category("Images")
    table._proxy_model.set_universal_search("file-", frozenset())
    table._proxy_model.set_universal_search("", frozenset())
    table._proxy_model.set_category("")

    assert selection.selected_ids() == set(expected_ids)
    for row, record in enumerate(records):
        index = table._source_model.index(row, table._source_model.SELECTION_COLUMN)
        expected = Qt.CheckState.Checked if str(record["file_id"]) in expected_ids else Qt.CheckState.Unchecked
        assert table._source_model.data(index, Qt.ItemDataRole.CheckStateRole) == expected


def test_selection_header_neutralizes_its_non_business_sort_key(qtbot):
    table = FileTable(file_selection=FileSelectionModel())
    qtbot.addWidget(table)
    table.set_files(_records(4))

    table._proxy_model.sort(table._source_model.SELECTION_COLUMN, Qt.SortOrder.AscendingOrder)
    assert table._proxy_model.sortColumn() == table._source_model.SELECTION_COLUMN

    table._handle_header_click(table._source_model.SELECTION_COLUMN)

    assert table._proxy_model.sortColumn() == -1
    assert table.view.horizontalHeader().sortIndicatorSection() == -1


def test_selection_header_preserves_an_existing_business_sort(qtbot):
    table = FileTable(file_selection=FileSelectionModel())
    qtbot.addWidget(table)
    table.set_files(_records(4))
    table.restore_sort_state(3, Qt.SortOrder.AscendingOrder)

    table._handle_header_click(table._source_model.SELECTION_COLUMN)

    assert table._proxy_model.sortColumn() == 3


def test_business_name_and_size_sorts_survive_category_changes(qtbot):
    table = FileTable(file_selection=FileSelectionModel())
    qtbot.addWidget(table)
    records = (
        {"file_id": str(uuid4()), "name": "z.jpg", "category": "Images", "size": 30},
        {"file_id": str(uuid4()), "name": "a.jpg", "category": "Images", "size": 10},
        {"file_id": str(uuid4()), "name": "m.pdf", "category": "Documents", "size": 20},
    )
    table.set_files(records)

    table.restore_sort_state(3, Qt.SortOrder.AscendingOrder)
    table._proxy_model.set_category("Images")
    assert [table.record_for_index(table._proxy_model.index(row, 3))["name"] for row in range(2)] == [
        "a.jpg",
        "z.jpg",
    ]

    table.restore_sort_state(table._source_model.SIZE_COLUMN, Qt.SortOrder.DescendingOrder)
    table._proxy_model.set_category("Documents")
    assert table._proxy_model.sortColumn() == table._source_model.SIZE_COLUMN
    assert table.record_for_index(table._proxy_model.index(0, 3))["name"] == "m.pdf"
