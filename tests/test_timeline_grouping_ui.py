"""Projection hiérarchique réelle de la Timeline, sans modifier les événements métier."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QToolButton

from selection.file_selection import FileSelectionModel
from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.model import TimelineFilterProxyModel, TimelineTableModel
from timeline.service import TimelineService
from timeline.source import EXIF, EXIF_CAPTURED, FILE_MODIFIED, FILESYSTEM
from ui.file_table import FileTable
from ui.timeline_view import TimelineView


def test_timeline_does_not_display_the_legacy_inactive_grouping_control(qtbot):
    view = TimelineView(TimelineService(TimelineManager(())))
    qtbot.addWidget(view)

    assert not hasattr(view, "grouping")
    assert all(combo.currentText() != "Fichier" for combo in view.findChildren(QComboBox))


def test_timeline_selection_column_is_the_first_visible_column(qtbot):
    view = TimelineView(TimelineService(TimelineManager(())))
    qtbot.addWidget(view)

    assert TimelineTableModel.COLUMNS[TimelineTableModel.SELECTION_COLUMN] == "☐"
    assert TimelineTableModel.COLUMNS[1:6] == ("Date", "Heure", "Nom", "Catégorie", "Type d'événement")
    assert view.table.header().visualIndex(TimelineTableModel.SELECTION_COLUMN) == 0


def test_file_is_a_real_parent_with_its_events_as_children():
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    record = {"file_id": str(uuid4()), "name": "f7178336.jpg"}
    model = TimelineTableModel()
    model.set_events(
        (
            TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, file_record=record),
            TimelineEvent(EXIF_CAPTURED, moment + timedelta(seconds=1), EXIF, file_record=record),
        )
    )

    parent = model.index(0, 0)
    assert model.rowCount() == 1
    assert model.data(model.index(0, 3)) == "📄 f7178336.jpg"
    assert model.rowCount(parent) == 2
    assert model.parent(model.index(0, 0, parent)) == parent
    assert model.data(model.index(0, 5, parent)) == "💾 Modification du fichier"


def test_filter_keeps_a_file_parent_when_one_of_its_children_matches():
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    record = {"file_id": str(uuid4()), "name": "f7178336.jpg", "category": "Images"}
    model = TimelineTableModel()
    model.set_events(
        (
            TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, file_record=record),
            TimelineEvent(EXIF_CAPTURED, moment + timedelta(seconds=1), EXIF, file_record=record),
        )
    )
    proxy = TimelineFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.set_filters("prise de vue", "", "")

    parent = proxy.index(0, 0)
    assert proxy.rowCount() == 1
    assert proxy.rowCount(parent) == 1
    assert proxy.event_for_index(proxy.index(0, 0, parent)).event_type == EXIF_CAPTURED


def test_thousands_of_events_are_grouped_without_proxy_recursion():
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    file_ids = [str(uuid4()) for _ in range(2_000)]
    events = tuple(
        TimelineEvent(
            FILE_MODIFIED,
            moment + timedelta(seconds=index),
            FILESYSTEM,
            file_record={"file_id": file_ids[index // 3], "name": f"file-{index // 3}.jpg"},
        )
        for index in range(6_000)
    )
    model = TimelineTableModel()
    model.set_events(events)
    proxy = TimelineFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.sort(1)

    assert model.rowCount() == 2_000
    first = model.index(0, 0)
    assert model.rowCount(first) == 3
    assert proxy.rowCount() == 2_000


def test_repeated_incremental_batch_keeps_one_parent_and_one_event():
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    record = {"file_id": str(uuid4()), "name": "f7178336.jpg"}
    event = TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, event_id="stable-event", file_record=record)
    model = TimelineTableModel()

    model.append_events((event,))
    model.append_events((event,))

    parent = model.index(0, 0)
    assert model.rowCount() == 1
    assert model.rowCount(parent) == 1
    assert model.event_for_id("stable-event") is event


def test_complete_reconstruction_is_idempotent_for_duplicate_event_ids():
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    record = {"file_id": str(uuid4()), "name": "f7178336.jpg"}
    event = TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, event_id="stable-event", file_record=record)
    model = TimelineTableModel()

    model.set_events((event, event))

    assert model.rowCount() == 1
    assert model.rowCount(model.index(0, 0)) == 1


def test_equal_sha256_with_distinct_file_ids_remains_two_timeline_parents():
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    sha256 = "a" * 64
    first = {"file_id": str(uuid4()), "name": "first.jpg", "sha256": sha256}
    second = {"file_id": str(uuid4()), "name": "second.jpg", "sha256": sha256}
    model = TimelineTableModel()

    model.set_events(
        (
            TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, event_id="first", file_record=first),
            TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, event_id="second", file_record=second),
        )
    )

    assert model.rowCount() == 2


def test_timeline_parent_checkbox_shares_the_canonical_file_selection(qtbot):
    selection = FileSelectionModel()
    record = {"file_id": str(uuid4()), "name": "f7178336.jpg", "category": "Images"}
    event = TimelineEvent(FILE_MODIFIED, datetime(2025, 3, 20, tzinfo=UTC), FILESYSTEM, file_record=record)
    timeline = TimelineTableModel(file_selection=selection)
    files = FileTable(file_selection=selection)
    qtbot.addWidget(files)
    files.set_files((record,))
    timeline.set_events((event,))
    resets = []
    timeline.modelReset.connect(lambda: resets.append(True))

    parent = timeline.index(0, timeline.SELECTION_COLUMN)
    assert timeline.setData(parent, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)

    assert selection.contains(record["file_id"])
    source = files._source_model.index(0, files._source_model.SELECTION_COLUMN)
    assert files._source_model.data(source, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert not resets
    child = timeline.index(0, timeline.SELECTION_COLUMN, timeline.index(0, 0))
    assert not timeline.flags(child) & Qt.ItemFlag.ItemIsUserCheckable


def test_timeline_header_selects_only_visible_file_parents(qtbot):
    selection = FileSelectionModel()
    view = TimelineView(TimelineService(TimelineManager(())), file_selection=selection)
    qtbot.addWidget(view)
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    records = tuple(
        {"file_id": str(uuid4()), "name": f"file-{index}.jpg", "category": "Images" if index % 2 else "Documents"}
        for index in range(10)
    )
    view._model.append_events(
        tuple(
            TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, event_id=str(index), file_record=record)
            for index, record in enumerate(records)
        )
    )
    view._proxy.set_filters("", "Images", "")

    view._toggle_header_selection(TimelineTableModel.SELECTION_COLUMN)
    assert selection.selected_ids() == {record["file_id"] for record in records if record["category"] == "Images"}
    view._toggle_header_selection(TimelineTableModel.SELECTION_COLUMN)
    assert selection.count == 0


def test_timeline_checkbox_selection_survives_sort_filter_and_search(qtbot):
    selection = FileSelectionModel()
    view = TimelineView(TimelineService(TimelineManager(())), file_selection=selection)
    qtbot.addWidget(view)
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    records = tuple(
        {"file_id": str(uuid4()), "name": f"file-{index}.jpg", "category": "Images" if index % 2 else "Documents"}
        for index in range(6)
    )
    view._model.append_events(
        tuple(
            TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, event_id=str(index), file_record=record)
            for index, record in enumerate(records)
        )
    )
    selected = {records[1]["file_id"], records[4]["file_id"]}
    selection.select_many(selected)

    view._proxy.sort(3, Qt.SortOrder.DescendingOrder)
    view._proxy.set_filters("file", "Images", "")
    view._proxy.set_filters("", "", "")

    assert selection.selected_ids() == selected


def test_timeline_batch_commands_use_the_shared_checkbox_selection(qtbot):
    selection = FileSelectionModel()
    view = TimelineView(TimelineService(TimelineManager(())), file_selection=selection)
    qtbot.addWidget(view)
    selected = {str(uuid4()), str(uuid4())}
    received = []
    view.bulk_investigation_requested.connect(received.append)
    selection.select_many(selected)

    button = next(
        button for button in view.bulk_bar.findChildren(QToolButton) if button.text() == "Ajouter à Investigation"
    )
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert received == [selected]
