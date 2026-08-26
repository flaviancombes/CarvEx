from bookmarks.model import BookmarkKey
from bookmarks.service import BookmarkService


def test_bookmarks_are_indexed_and_bulk_toggle_is_atomic():
    service = BookmarkService()
    file_key = BookmarkKey("file", "file-1")

    result = service.add_many((file_key, file_key))

    assert result.added_keys == (file_key,)
    assert service.contains(file_key)
    assert service.count_by_kind() == {"file": 1}

    toggled = service.toggle_many((file_key,))

    assert toggled.removed_keys == (file_key,)
    assert service.count() == 0


def test_new_bookmark_workflows_reject_a_timeline_event_identity():
    service = BookmarkService()

    try:
        service.add(BookmarkKey("timeline_event", "file-1:filesystem.modified:0"))
    except ValueError as error:
        assert "file_id" in str(error)
    else:
        raise AssertionError("Un nouveau bookmark Timeline ne doit jamais être créé.")
