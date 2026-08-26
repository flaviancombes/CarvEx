"""Source unique de vérité et diffusion ciblée des bookmarks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QObject, Signal

from bookmarks.model import Bookmark, BookmarkKey, BookmarkPriority, canonicalize_legacy_bookmark
from bookmarks.repository import BookmarkRepository, InMemoryBookmarkRepository


@dataclass(frozen=True, slots=True)
class BookmarkBatchResult:
    added_keys: tuple[BookmarkKey, ...] = ()
    removed_keys: tuple[BookmarkKey, ...] = ()
    unchanged_keys: tuple[BookmarkKey, ...] = ()

    @property
    def changed_keys(self) -> tuple[BookmarkKey, ...]:
        return self.added_keys + self.removed_keys


class BookmarkService(QObject):
    """Maintient un index O(1), sans connaître les vues ni les sujets concrets."""

    bookmarks_changed = Signal(object)
    bookmarks_batch_changed = Signal(object)
    bookmarks_reset = Signal()

    def __init__(self, repository: BookmarkRepository | None = None, parent=None) -> None:
        super().__init__(parent)
        self._repository = repository or InMemoryBookmarkRepository()
        self._bookmarks = self._load_canonical_bookmarks()
        self._kind_counts = Counter(bookmark.subject_kind for bookmark in self._bookmarks.values())
        self._priority_counts = Counter(bookmark.priority for bookmark in self._bookmarks.values())
        self._collection_counts = Counter(bookmark.collection_id for bookmark in self._bookmarks.values())
        self._tag_counts = Counter(tag for bookmark in self._bookmarks.values() for tag in bookmark.tags)

    def contains(self, key: BookmarkKey) -> bool:
        return key in self._bookmarks

    def get(self, key: BookmarkKey) -> Bookmark | None:
        return self._bookmarks.get(key)

    def all(self) -> tuple[Bookmark, ...]:
        return tuple(self._bookmarks.values())

    def attach_repository(self, repository: BookmarkRepository) -> None:
        """Rattache le service au repository du nouveau projet actif."""
        self._repository = repository
        self._bookmarks = self._load_canonical_bookmarks()
        self._kind_counts = Counter(bookmark.subject_kind for bookmark in self._bookmarks.values())
        self._priority_counts = Counter(bookmark.priority for bookmark in self._bookmarks.values())
        self._collection_counts = Counter(bookmark.collection_id for bookmark in self._bookmarks.values())
        self._tag_counts = Counter(tag for bookmark in self._bookmarks.values() for tag in bookmark.tags)
        self.bookmarks_reset.emit()

    def add(self, key: BookmarkKey) -> Bookmark | None:
        result = self.add_many((key,))
        return self._bookmarks.get(result.added_keys[0]) if result.added_keys else None

    def remove(self, key: BookmarkKey) -> bool:
        return bool(self.remove_many((key,)).removed_keys)

    def toggle(self, key: BookmarkKey) -> BookmarkBatchResult:
        return self.toggle_many((key,))

    def add_many(self, keys: Iterable[BookmarkKey]) -> BookmarkBatchResult:
        result, created = self._add_many(keys)
        if created:
            self._repository.save_many(created)
        return self._publish(result)

    def remove_many(self, keys: Iterable[BookmarkKey]) -> BookmarkBatchResult:
        result = self._remove_many(keys)
        if result.removed_keys:
            self._repository.delete_many(result.removed_keys)
        return self._publish(result)

    def toggle_many(self, keys: Iterable[BookmarkKey]) -> BookmarkBatchResult:
        keys = tuple(self._unique(keys))
        present = tuple(key for key in keys if key in self._bookmarks)
        absent = tuple(key for key in keys if key not in self._bookmarks)
        removed_result = self._remove_many(present)
        added_result, created = self._add_many(absent)
        if removed_result.removed_keys:
            self._repository.delete_many(removed_result.removed_keys)
        if created:
            self._repository.save_many(created)
        return self._publish(BookmarkBatchResult(added_result.added_keys, removed_result.removed_keys))

    def _add_many(self, keys: Iterable[BookmarkKey]) -> tuple[BookmarkBatchResult, list[Bookmark]]:
        added: list[BookmarkKey] = []
        unchanged: list[BookmarkKey] = []
        created: list[Bookmark] = []
        for key in self._unique(keys):
            self._require_canonical_key(key)
            if key in self._bookmarks:
                unchanged.append(key)
                continue
            bookmark = Bookmark(key.subject_kind, key.subject_id, datetime.now(UTC))
            self._bookmarks[key] = bookmark
            self._increment_counts(bookmark)
            added.append(key)
            created.append(bookmark)
        return BookmarkBatchResult(tuple(added), (), tuple(unchanged)), created

    def _remove_many(self, keys: Iterable[BookmarkKey]) -> BookmarkBatchResult:
        removed: list[BookmarkKey] = []
        unchanged: list[BookmarkKey] = []
        for key in self._unique(keys):
            if key not in self._bookmarks:
                unchanged.append(key)
                continue
            bookmark = self._bookmarks.pop(key)
            self._decrement_counts(bookmark)
            removed.append(key)
        return BookmarkBatchResult((), tuple(removed), tuple(unchanged))

    def count(self) -> int:
        return len(self._bookmarks)

    def count_by_kind(self) -> Mapping[str, int]:
        return dict(self._kind_counts)

    def count_by_priority(self) -> Mapping[BookmarkPriority | None, int]:
        return dict(self._priority_counts)

    def count_by_collection(self) -> Mapping[str | None, int]:
        return dict(self._collection_counts)

    def count_by_tag(self) -> Mapping[str, int]:
        return dict(self._tag_counts)

    def _publish(self, result: BookmarkBatchResult) -> BookmarkBatchResult:
        if result.changed_keys:
            self.bookmarks_changed.emit(result.changed_keys)
            self.bookmarks_batch_changed.emit(result)
        return result

    def _increment_counts(self, bookmark: Bookmark) -> None:
        self._kind_counts[bookmark.subject_kind] += 1
        self._priority_counts[bookmark.priority] += 1
        self._collection_counts[bookmark.collection_id] += 1
        self._tag_counts.update(bookmark.tags)

    def _decrement_counts(self, bookmark: Bookmark) -> None:
        for index, value in (
            (self._kind_counts, bookmark.subject_kind),
            (self._priority_counts, bookmark.priority),
            (self._collection_counts, bookmark.collection_id),
        ):
            index[value] -= 1
            if not index[value]:
                del index[value]
        for tag in bookmark.tags:
            self._tag_counts[tag] -= 1
            if not self._tag_counts[tag]:
                del self._tag_counts[tag]

    @staticmethod
    def _unique(keys: Iterable[BookmarkKey]) -> Iterable[BookmarkKey]:
        return dict.fromkeys(keys)

    def _load_canonical_bookmarks(self) -> dict[BookmarkKey, Bookmark]:
        """Lit les projets anciens et persiste immédiatement leur forme canonique."""
        loaded = tuple(self._repository.load())
        canonical: dict[BookmarkKey, Bookmark] = {}
        unresolved: list[Bookmark] = []
        migrated = False
        for bookmark in loaded:
            converted = canonicalize_legacy_bookmark(bookmark)
            if converted is None:
                # Une valeur historique sans file_id ne peut pas être devinée ni
                # réécrite ; elle reste dans le backend pour une récupération manuelle.
                unresolved.append(bookmark)
                continue
            migrated |= converted != bookmark
            canonical.setdefault(converted.key, converted)
        if migrated:
            self._repository.replace_all((*canonical.values(), *unresolved))
        return canonical

    @staticmethod
    def _require_canonical_key(key: BookmarkKey) -> None:
        if key.subject_kind != "file" or not key.subject_id.strip():
            raise ValueError("Les nouveaux bookmarks doivent référencer un file_id.")
