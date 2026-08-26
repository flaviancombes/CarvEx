"""Contrat de persistance échangeable des bookmarks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from bookmarks.model import Bookmark, BookmarkKey


class BookmarkRepository(ABC):
    @abstractmethod
    def load(self) -> Iterable[Bookmark]: ...

    @abstractmethod
    def save_many(self, bookmarks: Iterable[Bookmark]) -> None: ...

    @abstractmethod
    def delete_many(self, keys: Iterable[BookmarkKey]) -> None: ...

    @abstractmethod
    def replace_all(self, bookmarks: Iterable[Bookmark]) -> None: ...


class InMemoryBookmarkRepository(BookmarkRepository):
    """Stockage initial remplaçable par JSON, SQLite ou projet .carvex."""

    def __init__(self, bookmarks: Iterable[Bookmark] = ()) -> None:
        self._bookmarks = {bookmark.key: bookmark for bookmark in bookmarks}

    def load(self) -> Iterable[Bookmark]:
        return tuple(self._bookmarks.values())

    def save_many(self, bookmarks: Iterable[Bookmark]) -> None:
        for bookmark in bookmarks:
            self._bookmarks[bookmark.key] = bookmark

    def delete_many(self, keys: Iterable[BookmarkKey]) -> None:
        for key in keys:
            self._bookmarks.pop(key, None)

    def replace_all(self, bookmarks: Iterable[Bookmark]) -> None:
        self._bookmarks = {bookmark.key: bookmark for bookmark in bookmarks}
