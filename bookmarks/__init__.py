"""Bookmarks génériques pour les objets métier CarvEx."""

from bookmarks.model import Bookmark, BookmarkColor, BookmarkKey, BookmarkPriority
from bookmarks.repository import BookmarkRepository, InMemoryBookmarkRepository
from bookmarks.service import BookmarkBatchResult, BookmarkService

__all__ = (
    "Bookmark",
    "BookmarkBatchResult",
    "BookmarkColor",
    "BookmarkKey",
    "BookmarkPriority",
    "BookmarkRepository",
    "BookmarkService",
    "InMemoryBookmarkRepository",
)
