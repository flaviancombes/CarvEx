"""Projection utilisateur des bookmarks canoniques."""

from __future__ import annotations

from uuid import uuid4

from bookmarks.model import BookmarkKey
from bookmarks.qt_model import BookmarkModel
from bookmarks.repository import InMemoryBookmarkRepository
from bookmarks.service import BookmarkService
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.resolver import FileSelectionRegistry


def test_bookmark_projection_uses_file_fields_never_the_technical_identity():
    file_id = str(uuid4())
    record = {"file_id": file_id, "name": "contrat.pdf", "category": "Documents", "mime": "application/pdf"}
    registry = FileSelectionRegistry()
    registry.set_records((record,))
    service = BookmarkService(InMemoryBookmarkRepository())
    service.add(BookmarkKey("file", file_id))
    model = BookmarkModel(service, entity_resolver=CanonicalEntityResolver(registry))

    assert model.data(model.index(0, 1)) == "contrat.pdf"
    assert model.data(model.index(0, 2)) == "Documents"
    assert model.data(model.index(0, 3)) == "application/pdf"
    assert file_id not in {str(model.data(model.index(0, column))) for column in range(model.columnCount())}


def test_investigation_marker_refresh_is_limited_to_changed_canonical_bookmarks():
    file_ids = tuple(str(uuid4()) for _ in range(20))
    service = BookmarkService(InMemoryBookmarkRepository())
    service.add_many(BookmarkKey("file", file_id) for file_id in file_ids)
    model = BookmarkModel(service)
    changes = []
    resets = []
    model.dataChanged.connect(lambda first, last, _roles: changes.append((first.row(), last.row())))
    model.modelReset.connect(lambda: resets.append(True))

    model.refresh_investigation_markers(file_ids[:5])

    assert changes == [(row, row) for row in range(5)]
    assert not resets
