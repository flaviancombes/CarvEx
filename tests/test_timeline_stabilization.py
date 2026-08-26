"""Régressions Qt du modèle Timeline hiérarchique."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtWidgets import QApplication, QTreeView

from bookmarks.model import BookmarkKey
from bookmarks.repository import InMemoryBookmarkRepository
from bookmarks.service import BookmarkService
from timeline.event import TimelineEvent
from timeline.model import TimelineFilterProxyModel, TimelineTableModel
from timeline.source import FILE_CREATED, FILE_MODIFIED, FILESYSTEM


def _events() -> tuple[TimelineEvent, TimelineEvent, TimelineEvent]:
    first = {"file_id": str(uuid4()), "name": "alpha.jpg", "category": "Images"}
    second = {"file_id": str(uuid4()), "name": "beta.jpg", "category": "Images"}
    return (
        TimelineEvent(FILE_CREATED, datetime(2025, 1, 1), FILESYSTEM, file_record=first),
        TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM, file_record=first),
        TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 2, tzinfo=UTC), FILESYSTEM, file_record=second),
    )


def test_tree_view_filtering_has_no_parent_proxy_recursion():
    QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])
    model = TimelineTableModel()
    model.set_events(_events())
    proxy = TimelineFilterProxyModel()
    proxy.setSourceModel(model)
    tree = QTreeView()
    tree.setModel(proxy)

    proxy.set_filters("création", "", "")
    tree.show()
    QApplication.processEvents()

    parent = proxy.index(0, 0)
    assert proxy.rowCount() == 1
    assert proxy.rowCount(parent) == 1


def test_mixed_naive_and_aware_dates_keep_a_single_parent_and_sort_safely():
    model = TimelineTableModel()
    model.set_events(_events())
    proxy = TimelineFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.sort(1)
    assert model.rowCount() == 2
    assert model.rowCount(model.index(0, 0)) == 2


def test_sorting_bookmark_keeps_file_nodes_and_event_children_together():
    events = _events()
    service = BookmarkService(InMemoryBookmarkRepository())
    service.add(BookmarkKey("file", events[0].file_record["file_id"]))
    model = TimelineTableModel(bookmark_service=service)
    model.set_events(events)
    proxy = TimelineFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.sort(model.BOOKMARK_COLUMN)

    assert proxy.rowCount() == 2
    for row in range(proxy.rowCount()):
        assert proxy.rowCount(proxy.index(row, 0)) >= 1
