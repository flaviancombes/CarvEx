"""Algorithmic safeguards for large Timeline projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from threading import get_ident
from uuid import UUID, uuid4

import pytest
from PySide6.QtCore import Qt

from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.model import TimelineFilterProxyModel, TimelineTableModel
from timeline.repository import TimelineRepository
from timeline.service import TimelineService
from timeline.source import FILE_MODIFIED, FILESYSTEM
from ui.timeline_view import TimelineView


def _events(file_count: int, events_per_file: int = 3) -> tuple[TimelineEvent, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    records = [
        {"file_id": str(uuid4()), "name": f"file-{file_index}.jpg", "category": "Images"}
        for file_index in range(file_count)
    ]
    return tuple(
        TimelineEvent(
            FILE_MODIFIED,
            start + timedelta(seconds=file_index * events_per_file + event_index),
            FILESYSTEM,
            file_record=records[file_index],
        )
        for file_index in range(file_count)
        for event_index in range(events_per_file)
    )


def test_lazy_append_batches_new_file_nodes_into_one_qt_insertion():
    model = TimelineTableModel()
    inserted = []
    model.rowsInserted.connect(lambda parent, first, last: inserted.append((parent.isValid(), first, last)))

    model.append_events(_events(2_000))

    assert model.rowCount() == 2_000
    assert inserted == [(False, 0, 1_999)]


def test_incremental_deduplication_does_not_copy_the_existing_event_index():
    class _NoIterationDict(dict):
        def __iter__(self):
            raise AssertionError("The existing event index must not be copied for a new batch.")

    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    existing = TimelineEvent(
        FILE_MODIFIED,
        timestamp,
        FILESYSTEM,
        event_id="existing",
        file_record={"file_id": "file-1", "name": "existing.jpg"},
    )
    incoming = TimelineEvent(
        FILE_MODIFIED,
        timestamp,
        FILESYSTEM,
        event_id="new",
        file_record={"file_id": "file-2", "name": "new.jpg"},
    )
    model = TimelineTableModel()
    model.append_events((existing,))
    model._events_by_id = _NoIterationDict(model._events_by_id)

    model.append_events((existing, incoming))

    assert model.rowCount() == 2
    assert len(model._events_by_id) == 2


def test_file_parent_reuses_the_cached_earliest_event_for_display_and_sorting():
    events = list(_events(1, 3))
    events.reverse()
    model = TimelineTableModel()
    model.set_events(events)

    assert model.data(model.index(0, 1)) == "2025-01-01"
    assert model.data(model.index(0, 1), model.SORT_ROLE) == "2025-01-01T00:00:00+00:00"


def test_search_text_is_reused_while_the_user_refines_a_query(monkeypatch):
    model = TimelineTableModel()
    model.set_events(_events(100, 2))
    proxy = TimelineFilterProxyModel()
    proxy.setSourceModel(model)

    calls = 0
    from timeline import model as timeline_model

    original = timeline_model.searchable_text

    def count_search_text(event):
        nonlocal calls
        calls += 1
        return original(event)

    monkeypatch.setattr(timeline_model, "searchable_text", count_search_text)
    proxy.set_filters("file", "", "")
    assert proxy.rowCount() == 100
    first_query_calls = calls

    proxy.set_filters("modification", "", "")
    assert proxy.rowCount() == 100
    assert calls == first_query_calls

    model.set_events(_events(1))
    assert not proxy._search_texts


class _Engine:
    def events_for(self, record):
        return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM, file_record=record),)

    def clear_cache(self) -> None:
        pass


def test_build_session_yields_before_a_large_batch_exhausts_the_ui_budget(monkeypatch):
    repository = TimelineRepository(_Engine())
    repository.set_records(tuple({"file_id": str(uuid4()), "name": f"file-{index}.jpg"} for index in range(100)))
    session = repository.start_build()
    ticks = iter((0.0, 0.020))
    monkeypatch.setattr("timeline.repository.perf_counter", lambda: next(ticks))

    events, complete = session.next_batch(100, time_budget_ms=12)

    assert len(events) == 1
    assert not complete


class _LazyRecords(Sequence[Mapping[str, object]]):
    """Sequence-shaped fixture that never allocates its full simulated corpus."""

    def __init__(self, count: int) -> None:
        self._count = count

    def __len__(self) -> int:
        return self._count

    def __getitem__(self, index: int) -> Mapping[str, object]:
        if index < 0 or index >= self._count:
            raise IndexError(index)
        return {"file_id": str(UUID(int=index + 1)), "name": f"file-{index}.jpg"}


class _CountingEngine:
    def __init__(self) -> None:
        self.calls = 0

    def clear_cache(self) -> None:
        pass

    def events_for(self, record: Mapping[str, object]) -> tuple[TimelineEvent, ...]:
        self.calls += 1
        return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM, file_record=record),)


@pytest.mark.parametrize("record_count", (50_000, 250_000, 1_000_000))
def test_large_corpora_materialize_only_the_requested_timeline_batch(record_count: int) -> None:
    engine = _CountingEngine()
    repository = TimelineRepository(engine)
    repository.set_records(_LazyRecords(record_count))
    session = repository.start_build(retain_events=False)

    events, complete = session.next_batch(256)

    assert len(events) == 256
    assert not complete
    assert engine.calls == 256
    assert repository._events is None


def test_fifty_thousand_events_require_one_root_insertion_notification() -> None:
    model = TimelineTableModel()
    insertions = []
    model.rowsInserted.connect(lambda parent, first, last: insertions.append((parent.isValid(), first, last)))
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    events = tuple(
        TimelineEvent(
            FILE_MODIFIED,
            timestamp,
            FILESYSTEM,
            file_record={"file_id": str(UUID(int=index + 1)), "name": f"file-{index}.jpg"},
        )
        for index in range(50_000)
    )

    model.append_events(events)

    assert model.rowCount() == 50_000
    assert insertions == [(False, 0, 49_999)]


def test_timeline_view_extracts_events_outside_the_qt_thread(qtbot) -> None:
    class _ThreadAwareExtractor:
        def __init__(self) -> None:
            self.thread_ids: set[int] = set()

        def extract(self, _record):
            self.thread_ids.add(get_ident())
            return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM),)

    extractor = _ThreadAwareExtractor()
    service = TimelineService(TimelineManager((extractor,)))
    service.set_records(
        tuple({"file_id": str(UUID(int=index + 1)), "name": f"file-{index}.jpg"} for index in range(100))
    )
    view = TimelineView(service)
    qtbot.addWidget(view)
    ui_thread_id = get_ident()

    view.load_events()

    qtbot.waitUntil(lambda: view._build_worker is None, timeout=10_000)
    assert view._model.rowCount() == 100
    assert extractor.thread_ids
    assert ui_thread_id not in extractor.thread_ids


def test_timeline_view_projects_multiple_worker_batches_in_one_bulk_checkpoint(qtbot) -> None:
    class _Extractor:
        def extract(self, _record):
            return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM),)

    service = TimelineService(TimelineManager((_Extractor(),)))
    service.set_records(
        tuple({"file_id": str(UUID(int=index + 1)), "name": f"file-{index}.jpg"} for index in range(5_000))
    )
    view = TimelineView(service)
    qtbot.addWidget(view)
    inserted = []
    view._model.rowsInserted.connect(lambda parent, first, last: inserted.append((parent.isValid(), first, last)))

    view.load_events()

    qtbot.waitUntil(lambda: view._build_worker is None, timeout=10_000)
    assert inserted == [(False, 0, 4_999)]
    assert view._proxy.sourceModel() is view._model
    assert view.table.updatesEnabled()


def test_timeline_view_builds_chronological_parents_without_proxy_sorting(monkeypatch, qtbot) -> None:
    class _DatedExtractor:
        def extract(self, record):
            return (TimelineEvent(FILE_MODIFIED, record["date"], FILESYSTEM),)

    calls = 0
    original = TimelineFilterProxyModel.lessThan

    def count_less_than(self, left, right):
        nonlocal calls
        calls += 1
        return original(self, left, right)

    monkeypatch.setattr(TimelineFilterProxyModel, "lessThan", count_less_than)
    service = TimelineService(TimelineManager((_DatedExtractor(),)))
    start = datetime(2025, 1, 1, tzinfo=UTC)
    service.set_records(
        tuple(
            {
                "file_id": str(UUID(int=index + 1)),
                "name": f"file-{index}.jpg",
                "date": start + timedelta(seconds=10 - index),
            }
            for index in range(10)
        )
    )
    view = TimelineView(service)
    qtbot.addWidget(view)

    view.load_events()

    qtbot.waitUntil(lambda: view._build_worker is None, timeout=10_000)

    dates = [view._model.event_at(row).date for row in range(view._model.rowCount())]
    assert dates == sorted(dates)
    assert calls == 0
    assert view.table.header().sortIndicatorSection() == 1
    assert view.table.header().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder


def test_timeline_view_uses_uniform_row_heights(qtbot) -> None:
    service = TimelineService(TimelineManager(()))
    view = TimelineView(service)
    qtbot.addWidget(view)

    assert view.table.uniformRowHeights()


def test_timeline_view_restores_an_explicit_workspace_sort(qtbot) -> None:
    class _NamedExtractor:
        def extract(self, record):
            return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM),)

    service = TimelineService(TimelineManager((_NamedExtractor(),)))
    service.set_records(
        (
            {"file_id": str(UUID(int=1)), "name": "alpha.jpg"},
            {"file_id": str(UUID(int=2)), "name": "zulu.jpg"},
        )
    )
    view = TimelineView(service)
    qtbot.addWidget(view)
    view.restore_sort_state(3, Qt.SortOrder.DescendingOrder)

    view.load_events()

    qtbot.waitUntil(lambda: view._build_worker is None, timeout=10_000)

    assert [view._proxy.index(row, 3).data() for row in range(view._proxy.rowCount())] == [
        "📄 zulu.jpg",
        "📄 alpha.jpg",
    ]
