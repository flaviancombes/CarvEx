"""Régressions de canonicalisation Fichiers / Timeline / Bookmarks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from bookmarks.model import BookmarkKey
from bookmarks.repository import InMemoryBookmarkRepository
from bookmarks.service import BookmarkService
from timeline.event import TimelineEvent
from timeline.model import TimelineTableModel
from timeline.source import FILE_CREATED, FILE_MODIFIED, FILESYSTEM


def _events() -> tuple[TimelineEvent, TimelineEvent]:
    record = {"file_id": str(uuid4()), "name": "evidence.jpg"}
    moment = datetime(2025, 3, 20, tzinfo=UTC)
    return (
        TimelineEvent(FILE_CREATED, moment, FILESYSTEM, file_record=record),
        TimelineEvent(FILE_MODIFIED, moment + timedelta(seconds=1), FILESYSTEM, file_record=record),
    )


def test_timeline_rows_share_the_file_bookmark_key_and_star():
    service = BookmarkService(InMemoryBookmarkRepository())
    model = TimelineTableModel(bookmark_service=service)
    events = _events()
    model.set_events(events)

    file_id = events[0].file_record["file_id"]
    parent = model.index(0, 0)
    assert model.bookmark_key_at(parent) == BookmarkKey("file", file_id)
    assert model.bookmark_key_at(model.index(0, 0, parent)) == BookmarkKey("file", file_id)
    assert model.bookmark_key_at(model.index(1, 0, parent)) == BookmarkKey("file", file_id)

    service.add(BookmarkKey("file", file_id))

    assert model.data(model.index(0, model.BOOKMARK_COLUMN)) == "★"
    assert model.data(model.index(0, model.BOOKMARK_COLUMN, parent)) == "★"
    assert model.data(model.index(1, model.BOOKMARK_COLUMN, parent)) == "★"
    assert service.count() == 1
