"""Régressions de sélection simple dans la projection Timeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt

from bookmarks.model import BookmarkKey
from bookmarks.repository import InMemoryBookmarkRepository
from bookmarks.service import BookmarkService
from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.model import TimelineTreeModel
from timeline.service import TimelineService
from timeline.source import EXIF, EXIF_CAPTURED, FILE_MODIFIED, FILESYSTEM
from ui.timeline_view import TimelineView


def _view(qtbot) -> tuple[TimelineView, tuple[TimelineEvent, TimelineEvent]]:
    view = TimelineView(TimelineService(TimelineManager(())))
    qtbot.addWidget(view)
    record = {"file_id": str(uuid4()), "name": "preuve.jpg", "category": "Images"}
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    events = (
        TimelineEvent(FILE_MODIFIED, moment, FILESYSTEM, event_id="event-modified", file_record=record),
        TimelineEvent(EXIF_CAPTURED, moment + timedelta(seconds=1), EXIF, event_id="event-exif", file_record=record),
    )
    view._model.append_events(events)
    view.show()
    qtbot.waitUntil(lambda: view._proxy.rowCount() == 1)
    return view, events


def _click(qtbot, view: TimelineView, index) -> None:
    view.table.scrollTo(index)
    qtbot.wait(10)
    qtbot.mouseClick(view.table.viewport(), Qt.MouseButton.LeftButton, pos=view.table.visualRect(index).center())


def test_parent_and_child_clicks_publish_one_selection_with_a_current_index(qtbot):
    view, events = _view(qtbot)
    selected: list[str] = []
    view.event_selected.connect(lambda event: selected.append(event.event_id))
    parent = view._proxy.index(0, 3)
    _click(qtbot, view, parent)

    assert selected == [events[0].event_id]
    assert view.table.currentIndex() == parent
    assert view._proxy.event_for_index(view.table.currentIndex()) is events[0]

    view._activate_index(parent)
    parent_node = parent.siblingAtColumn(0)
    qtbot.waitUntil(lambda: view.table.isExpanded(parent_node))
    child = view._proxy.index(1, 3, parent_node)
    _click(qtbot, view, child)

    assert selected == [events[0].event_id, events[1].event_id]
    assert view.table.currentIndex() == child
    assert view._proxy.event_for_index(view.table.currentIndex()) is events[1]


def test_event_selection_survives_targeted_investigation_marker_refresh(qtbot):
    view, events = _view(qtbot)
    parent = view._proxy.index(0, 3)
    view._activate_index(parent)
    parent_node = parent.siblingAtColumn(0)
    qtbot.waitUntil(lambda: view.table.isExpanded(parent_node))
    child = view._proxy.index(1, 3, parent_node)
    _click(qtbot, view, child)
    resets: list[bool] = []
    layouts: list[bool] = []
    view._model.modelReset.connect(lambda: resets.append(True))
    view._model.layoutChanged.connect(lambda: layouts.append(True))

    view.refresh_investigation_markers((events[0].file_record["file_id"],))

    assert view.table.currentIndex().isValid()
    assert view._proxy.event_for_index(view.table.currentIndex()) is events[1]
    assert not resets
    assert not layouts


def test_checkbox_selection_survives_targeted_investigation_marker_refresh(qtbot):
    view, events = _view(qtbot)
    checkbox = view._proxy.index(0, TimelineTreeModel.SELECTION_COLUMN)
    _click(qtbot, view, checkbox)

    view.refresh_investigation_markers((events[0].file_record["file_id"],))

    assert view.file_selection.selected_ids() == {events[0].file_record["file_id"]}
    assert checkbox.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked


def test_proxy_child_maps_to_the_exact_source_event(qtbot):
    view, events = _view(qtbot)
    parent = view._proxy.index(0, 0)
    child = view._proxy.index(1, 0, parent)
    source = view._proxy.mapToSource(child)

    assert source.isValid()
    assert view._model.event_for_index(source) is events[1]
    assert view._proxy.mapFromSource(source) == child
    assert view._model.event_for_id("missing-event") is None
    assert not view._proxy.index(99, 0).isValid()


def test_event_selection_survives_targeted_bookmark_marker_refresh(qtbot):
    bookmark_service = BookmarkService(InMemoryBookmarkRepository())
    view = TimelineView(TimelineService(TimelineManager(())), bookmark_service=bookmark_service)
    qtbot.addWidget(view)
    record = {"file_id": str(uuid4()), "name": "preuve.jpg", "category": "Images"}
    event = TimelineEvent(FILE_MODIFIED, datetime(2025, 3, 20, tzinfo=UTC), FILESYSTEM, file_record=record)
    view._model.append_events((event,))
    view.show()
    parent = view._proxy.index(0, 0)
    view._activate_index(parent)
    qtbot.waitUntil(lambda: view.table.isExpanded(parent))
    child = view._proxy.index(0, 3, parent)
    _click(qtbot, view, child)

    bookmark_service.add(BookmarkKey("file", record["file_id"]))

    assert view.table.currentIndex().isValid()
    assert view._proxy.event_for_index(view.table.currentIndex()) is event


def test_parent_checkbox_click_updates_the_shared_canonical_selection(qtbot):
    view, events = _view(qtbot)
    checkbox = view._proxy.index(0, TimelineTreeModel.SELECTION_COLUMN)

    _click(qtbot, view, checkbox)

    file_id = events[0].file_record["file_id"]
    assert view.file_selection.selected_ids() == {file_id}
    assert checkbox.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked

    _click(qtbot, view, checkbox)

    assert not view.file_selection.selected_ids()
    assert checkbox.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked


def test_checkbox_selection_is_unique_per_file_with_multiple_events(qtbot):
    view, events = _view(qtbot)
    first_parent = view._proxy.index(0, TimelineTreeModel.SELECTION_COLUMN)
    _click(qtbot, view, first_parent)
    view._activate_index(first_parent)
    child = view._proxy.index(1, TimelineTreeModel.SELECTION_COLUMN, first_parent)

    assert not (view._proxy.flags(child) & Qt.ItemFlag.ItemIsUserCheckable)
    assert view.file_selection.selected_ids() == {events[0].file_record["file_id"]}


def test_header_selection_state_tracks_timeline_nodes(qtbot):
    view, events = _view(qtbot)
    second_record = {"file_id": str(uuid4()), "name": "seconde.jpg", "category": "Images"}
    view._model.append_events(
        (TimelineEvent(FILE_MODIFIED, datetime(2025, 3, 21, tzinfo=UTC), FILESYSTEM, file_record=second_record),)
    )

    def header_state():
        return view._model.headerData(
            TimelineTreeModel.SELECTION_COLUMN, Qt.Orientation.Horizontal, Qt.ItemDataRole.CheckStateRole
        )

    assert header_state() == Qt.CheckState.Unchecked
    view.file_selection.select_many((events[0].file_record["file_id"],))
    assert header_state() == Qt.CheckState.PartiallyChecked
    view.file_selection.select_many((second_record["file_id"],))
    assert header_state() == Qt.CheckState.Checked


def test_bulk_investigation_receives_one_batch_of_checked_file_ids(qtbot):
    view, events = _view(qtbot)
    additional_ids = [str(uuid4()) for _ in range(4)]
    view._model.append_events(
        tuple(
            TimelineEvent(
                FILE_MODIFIED,
                datetime(2025, 3, 22, tzinfo=UTC) + timedelta(seconds=index),
                FILESYSTEM,
                file_record={"file_id": file_id, "name": f"preuve-{index}.jpg", "category": "Images"},
            )
            for index, file_id in enumerate(additional_ids)
        )
    )
    expected = {events[0].file_record["file_id"], *additional_ids}
    view.file_selection.select_many(expected)
    batches: list[set[str]] = []
    view.bulk_investigation_requested.connect(lambda file_ids: batches.append(set(file_ids)))

    next(
        button
        for button in view.bulk_bar.findChildren(type(view.bulk_label))
        if button.text() == "Ajouter à Investigation"
    ).click()

    assert batches == [expected]


def _large_model(file_count: int) -> tuple[TimelineTreeModel, tuple[str, ...]]:
    model = TimelineTreeModel()
    file_ids = tuple(str(uuid4()) for _ in range(file_count))
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    model.set_events(
        tuple(
            TimelineEvent(
                FILE_MODIFIED,
                moment + timedelta(seconds=index),
                FILESYSTEM,
                event_id=f"event-{index}",
                file_record={"file_id": file_id, "name": f"file-{index}.jpg", "category": "Images"},
            )
            for index, file_id in enumerate(file_ids)
        )
    )
    return model, file_ids


@pytest.mark.parametrize("file_count", (1_000, 10_000, 50_000))
def test_large_bulk_selection_emits_one_bounded_notification_without_model_reset(file_count: int):
    model, file_ids = _large_model(file_count)
    data_changes: list[tuple] = []
    resets: list[bool] = []
    layouts: list[bool] = []
    model.dataChanged.connect(lambda *args: data_changes.append(args))
    model.modelReset.connect(lambda: resets.append(True))
    model.layoutChanged.connect(lambda: layouts.append(True))

    started_at = perf_counter()
    model._file_selection.select_many(file_ids)
    select_elapsed = perf_counter() - started_at

    assert model._file_selection.count == len(file_ids)
    assert len(data_changes) == 1
    assert not resets
    assert not layouts
    assert select_elapsed < 2.0

    data_changes.clear()
    started_at = perf_counter()
    model._file_selection.deselect_many(file_ids)
    clear_elapsed = perf_counter() - started_at

    assert not model._file_selection.count
    assert len(data_changes) == 1
    assert not resets
    assert not layouts
    assert clear_elapsed < 2.0
