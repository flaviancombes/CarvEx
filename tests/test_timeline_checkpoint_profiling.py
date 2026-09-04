"""Instrumentation agrégée des checkpoints de projection Timeline."""

from __future__ import annotations

import gc
from datetime import UTC, datetime
from uuid import UUID

import pytest
from PySide6.QtCore import Qt

from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.model import TimelineFilterProxyModel, TimelineTableModel
from timeline.service import TimelineService
from timeline.source import FILE_CREATED, FILE_MODIFIED, FILESYSTEM
from ui.timeline_view import TimelineView
from utils import performance


def _events(file_count: int, events_per_file: int = 1, offset: int = 0) -> tuple[TimelineEvent, ...]:
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    records = tuple(
        {"file_id": str(UUID(int=file_number + offset + 1)), "name": f"file-{file_number + offset}.jpg"}
        for file_number in range(file_count)
    )
    return tuple(
        TimelineEvent(
            FILE_MODIFIED,
            timestamp,
            FILESYSTEM,
            event_id=f"{records[file_number]['file_id']}:filesystem.modified:{event_number}",
            file_record=records[file_number],
        )
        for file_number in range(file_count)
        for event_number in range(events_per_file)
    )


def test_append_metrics_describe_only_the_projection_delta():
    model = TimelineTableModel()
    first = _events(2, events_per_file=2)

    metrics = model.append_events(first)

    assert metrics.input_event_count == 4
    assert metrics.unique_event_count == 4
    assert metrics.inserted_parent_count == 2
    assert metrics.existing_parent_count == 0
    assert metrics.inserted_child_count == 4
    assert metrics.insert_signal_count == 1


def test_checkpoint_resolves_each_shared_file_record_once_and_reuses_its_bookmark_key():
    class CountingResolver:
        def __init__(self) -> None:
            self.file_id_calls = 0

        def file_id_for(self, event):
            self.file_id_calls += 1
            return event.file_record["file_id"]

        def bookmark_key_for(self, _event):
            raise AssertionError("append_events must reuse the resolved canonical file identity")

    record = {"file_id": "file-1", "name": "one.jpg"}
    events = tuple(
        TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM, file_record=record) for _ in range(3)
    )
    resolver = CountingResolver()
    model = TimelineTableModel(entity_resolver=resolver)

    model.append_events(events)

    assert resolver.file_id_calls == 1
    assert model._bookmark_nodes


def test_event_index_metrics_are_stable_across_progressive_checkpoints(monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    model = TimelineTableModel()
    indexed_count = 0

    for checkpoint in range(20):
        metrics = model.append_events(_events(1_000, events_per_file=3, offset=checkpoint * 1_000))

        assert metrics.event_index_size_before == indexed_count
        assert metrics.event_index_size_after == indexed_count + 3_000
        assert metrics.event_index_new_key_count == 3_000
        assert metrics.event_index_existing_key_count == 0
        assert metrics.duplicate_event_count == 0
        assert metrics.event_type_count == 1
        assert metrics.empty_event_id_count == 0
        assert all(collections >= 0 for collections in metrics.event_index_gc_collections)
        indexed_count += 3_000


def test_event_index_metrics_report_duplicate_events_and_multiple_types(monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    record = {"file_id": "file-1", "name": "one.jpg"}
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    created = TimelineEvent(FILE_CREATED, timestamp, FILESYSTEM, event_id="file-1:created:0", file_record=record)
    modified = TimelineEvent(FILE_MODIFIED, timestamp, FILESYSTEM, event_id="file-1:modified:0", file_record=record)
    model = TimelineTableModel()

    metrics = model.append_events((created, created, modified))

    assert metrics.unique_event_count == 2
    assert metrics.duplicate_event_count == 1
    assert metrics.event_type_count == 2
    assert metrics.event_index_new_key_count == 2
    assert metrics.event_index_size_before == 0
    assert metrics.event_index_size_after == 2


def test_event_index_gc_observer_is_scoped_to_performance_checkpoints(monkeypatch):
    model = TimelineTableModel()
    callbacks_before = tuple(gc.callbacks)

    model.append_events(_events(1))

    assert tuple(gc.callbacks) == callbacks_before

    monkeypatch.setattr(performance, "ENABLED", True)
    model.append_events(_events(1, offset=1))

    assert tuple(gc.callbacks) == callbacks_before


def test_event_index_metrics_observe_dict_capacity_at_the_real_checkpoint_16_threshold(monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    model = TimelineTableModel()
    sentinel = TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM)
    model._events_by_id = {f"prefill-{index}": sentinel for index in range(552_960)}

    metrics = model.append_events(_events(12_288, events_per_file=3, offset=552_960))

    assert metrics.event_index_size_before == 552_960
    assert metrics.event_index_size_after == 589_824
    assert metrics.event_index_new_key_count == 36_864
    assert metrics.event_dict_bytes_before > 0
    assert metrics.event_dict_bytes_after >= metrics.event_dict_bytes_before


@pytest.mark.parametrize("file_count", (1_000, 10_000, 50_000))
def test_checkpoint_projection_uses_one_grouped_root_insert_per_new_file_batch(file_count: int):
    model = TimelineTableModel()
    inserted: list[tuple[bool, int, int]] = []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((parent.isValid(), first, last)))

    metrics = model.append_events(_events(file_count))

    assert metrics.inserted_parent_count == file_count
    assert metrics.existing_parent_count == 0
    assert metrics.insert_signal_count == 1
    assert inserted == [(False, 0, file_count - 1)]


@pytest.mark.parametrize(
    ("file_count", "events_per_file"),
    ((1_000, 1), (10_000, 1), (50_000, 1), (10_000, 3), (12_288, 3), (16_384, 3)),
)
def test_checkpoint_profile_reports_delta_and_qt_signal_counts(qtbot, monkeypatch, caplog, file_count, events_per_file):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    view = TimelineView(TimelineService(TimelineManager(())))
    qtbot.addWidget(view)
    view._proxy.sort(-1)
    view._proxy.setDynamicSortFilter(False)
    view._proxy.set_building(True)
    view.table.setSortingEnabled(False)
    header = view.table.header()
    signals_blocked = header.blockSignals(True)
    try:
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    finally:
        header.blockSignals(signals_blocked)
    view._proxy.setSourceModel(None)
    view.table.setUpdatesEnabled(False)
    view._projection_proxy_attached = False
    view._pending_projection_batches.append(_events(file_count, events_per_file))

    view._project_next_batch()

    messages = [record.message for record in caplog.records if "[TimelineCheckpoint]" in record.message]
    assert messages
    assert f"pending_events={file_count * events_per_file}" in messages[-1]
    assert f"inserted_parents={file_count}" in messages[-1]
    assert f"inserted_children={file_count * events_per_file}" in messages[-1]
    assert "insert_signals=1" in messages[-1]
    assert "root_insert_signals=1" in messages[-1]
    assert "child_insert_signals=0" in messages[-1]
    assert "source_model_reset=0" in messages[-1]
    assert "proxy_model_reset=1" in messages[-1]
    assert "less_than_calls=0" in messages[-1]


def test_second_checkpoint_keeps_grouped_root_insertion_after_proxy_attachment(qtbot, monkeypatch, caplog):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    view = TimelineView(TimelineService(TimelineManager(())))
    qtbot.addWidget(view)
    view._proxy.sort(-1)
    view._proxy.setDynamicSortFilter(False)
    view._proxy.set_building(True)
    view.table.setSortingEnabled(False)
    header = view.table.header()
    signals_blocked = header.blockSignals(True)
    try:
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
    finally:
        header.blockSignals(signals_blocked)
    view._proxy.setSourceModel(None)
    view.table.setUpdatesEnabled(False)
    view._projection_proxy_attached = False
    view._pending_projection_batches.extend((_events(10_000, 3), _events(10_000, 3, offset=10_000)))

    view._project_next_batch()
    view._project_next_batch()

    messages = [record.message for record in caplog.records if "[TimelineCheckpoint]" in record.message]
    assert len(messages) == 2
    assert "checkpoint_index=2" in messages[-1]
    assert "inserted_parents=10000" in messages[-1]
    assert "child_insert_signals=0" in messages[-1]
    assert "proxy_model_reset=0" in messages[-1]
    assert "less_than_calls=0" in messages[-1]


def test_real_multi_checkpoint_build_does_not_reactivate_qtree_sorting(qtbot, monkeypatch):
    class Extractor:
        def extract(self, _record):
            return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM),)

    calls = 0
    original_less_than = TimelineFilterProxyModel.lessThan

    def count_less_than(proxy, left, right):
        nonlocal calls
        calls += 1
        return original_less_than(proxy, left, right)

    monkeypatch.setattr(TimelineFilterProxyModel, "lessThan", count_less_than)
    service = TimelineService(TimelineManager((Extractor(),)))
    service.set_records(
        tuple({"file_id": str(UUID(int=index + 1)), "name": f"file-{index}.jpg"} for index in range(12_289))
    )
    view = TimelineView(service)
    qtbot.addWidget(view)

    view.load_events()

    qtbot.waitUntil(lambda: view._build_worker is None, timeout=15_000)

    assert view._model.rowCount() == 12_289
    assert calls == 0
