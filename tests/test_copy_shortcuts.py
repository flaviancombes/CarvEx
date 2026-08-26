"""Régressions de copie : le presse-papiers reflète la cellule affichée."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtWidgets import QApplication

from bookmarks.model import BookmarkKey
from bookmarks.repository import InMemoryBookmarkRepository
from bookmarks.service import BookmarkService
from models.file_table_model import FileTableModel
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.resolver import FileSelectionRegistry
from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.service import TimelineService
from timeline.source import FILE_CREATED, FILESYSTEM
from ui.bookmarks_view import BookmarksView
from ui.file_table import FileTable
from ui.timeline_view import TimelineView


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _record() -> dict[str, object]:
    return {
        "file_id": str(uuid4()),
        "name": "f3561792.jpg",
        "category": "Images",
        "mime": "image/jpeg",
        "size": 1795,
        "sha256": "a" * 64,
        "output": "C:/Export/f3561792.jpg",
    }


def test_copy_shortcuts_copy_the_selected_display_value():
    app = _application()
    record = _record()
    registry = FileSelectionRegistry()
    registry.set_records((record,))
    resolver = CanonicalEntityResolver(registry)

    files = FileTable(entity_resolver=resolver)
    files.set_files((record,))
    for column, expected in (
        (3, "f3561792.jpg"),
        (4, "Images"),
        (5, "image/jpeg"),
        (6, "1,75 KiB"),
        (FileTableModel.DUPLICATE_COUNT_COLUMN, "1"),
        (FileTableModel.SHA256_COLUMN, "a" * 64),
    ):
        files.view.setCurrentIndex(files._proxy_model.index(0, column))
        files._shortcuts[4].activated.emit()
        assert app.clipboard().text() == expected
    files.view.setCurrentIndex(files._proxy_model.index(0, 0))
    files._shortcuts[4].activated.emit()
    assert app.clipboard().text() == "f3561792.jpg"

    event = TimelineEvent(FILE_CREATED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM, file_record=record)
    timeline = TimelineView(TimelineService(TimelineManager(())), entity_resolver=resolver)
    timeline._model.set_events((event,))
    for column in (1, 4, 5):
        index = timeline._proxy.index(0, column)
        timeline.table.setCurrentIndex(index)
        timeline._copy_shortcut.activated.emit()
        assert app.clipboard().text() == str(index.data())
    timeline.table.setCurrentIndex(timeline._proxy.index(0, 0))
    timeline._copy_shortcut.activated.emit()
    assert app.clipboard().text() == "f3561792.jpg"

    bookmarks_service = BookmarkService(InMemoryBookmarkRepository())
    bookmarks_service.add(BookmarkKey("file", str(record["file_id"])))
    bookmarks = BookmarksView(bookmarks_service, entity_resolver=resolver)
    for column, expected in ((1, "f3561792.jpg"), (2, "Images"), (3, "image/jpeg")):
        bookmarks.table.setCurrentIndex(bookmarks._model.index(0, column))
        bookmarks._copy_shortcut.activated.emit()
        assert app.clipboard().text() == expected
    bookmarks.table.setCurrentIndex(bookmarks._model.index(0, 0))
    bookmarks._copy_shortcut.activated.emit()
    assert app.clipboard().text() == "f3561792.jpg"
