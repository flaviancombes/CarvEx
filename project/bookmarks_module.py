"""Module de projet déclaratif qui fournit le repository des bookmarks."""

from __future__ import annotations

from collections.abc import Iterable

from bookmarks.model import Bookmark, BookmarkKey, canonicalize_legacy_bookmark
from bookmarks.repository import BookmarkRepository
from project.codecs import ProjectCodecRegistry, dataclass_codec, enum_codec
from project.migrations import ModuleMigrationService
from project.modules import ModuleDescriptor, ProjectModule, ProjectModuleContext
from project.stores import ProjectStore


class ProjectBookmarkRepository(BookmarkRepository):
    """Repository Bookmark dérivé d'un store logique, sans accès au support physique."""

    STORE_KEY = "bookmarks"

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    def load(self) -> Iterable[Bookmark]:
        return tuple(self._store.get(self.STORE_KEY, ()))

    def save_many(self, bookmarks: Iterable[Bookmark]) -> None:
        values = {bookmark.key: bookmark for bookmark in self.load()}
        values.update({bookmark.key: bookmark for bookmark in bookmarks})
        self._store.set(self.STORE_KEY, tuple(values.values()))

    def delete_many(self, keys: Iterable[BookmarkKey]) -> None:
        keys = set(keys)
        self._store.set(self.STORE_KEY, tuple(bookmark for bookmark in self.load() if bookmark.key not in keys))

    def replace_all(self, bookmarks: Iterable[Bookmark]) -> None:
        self._store.set(self.STORE_KEY, tuple(bookmarks))


class BookmarksProjectModule(ProjectModule):
    def register_codecs(self, registry: ProjectCodecRegistry) -> None:
        from bookmarks.model import BookmarkColor, BookmarkPriority

        registry.register_many(
            [
                dataclass_codec("dataclass:bookmarks.model.Bookmark", Bookmark),
                dataclass_codec("dataclass:bookmarks.model.BookmarkKey", BookmarkKey),
                enum_codec("enum:bookmarks.model.BookmarkColor", BookmarkColor),
                enum_codec("enum:bookmarks.model.BookmarkPriority", BookmarkPriority),
            ]
        )

    @property
    def descriptor(self) -> ModuleDescriptor:
        return ModuleDescriptor(
            module_id="bookmarks",
            schema_version=2,
            capabilities_provided=frozenset({"bookmarks"}),
            store_names=frozenset({"bookmarks"}),
        )

    def initialize(self, context: ProjectModuleContext) -> None:
        context.register_repository("bookmarks", ProjectBookmarkRepository(context.store("bookmarks")))

    def migrations(self) -> ModuleMigrationService:
        migrations = ModuleMigrationService("bookmarks")
        migrations.register(1, self._migrate_v1_to_v2)
        return migrations

    @staticmethod
    def _migrate_v1_to_v2(context: ProjectModuleContext) -> None:
        """Réécrit les références Timeline historiques vers leur file_id déterministe."""
        store = context.store(ProjectBookmarkRepository.STORE_KEY)
        values: dict[BookmarkKey, Bookmark] = {}
        for bookmark in store.get(ProjectBookmarkRepository.STORE_KEY, ()):
            converted = canonicalize_legacy_bookmark(bookmark)
            values.setdefault((converted or bookmark).key, converted or bookmark)
        store.set(ProjectBookmarkRepository.STORE_KEY, tuple(values.values()))
