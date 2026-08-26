"""Modèle métier typé des références bookmarkées."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class BookmarkColor(StrEnum):
    RED = "red"
    ORANGE = "orange"
    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"
    PURPLE = "purple"


class BookmarkPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class BookmarkKey:
    subject_kind: str
    subject_id: str


@dataclass(frozen=True, slots=True)
class Bookmark:
    """Référence légère et générique ; elle ne contient jamais les données du sujet."""

    subject_kind: str
    subject_id: str
    created_at: datetime
    note: str | None = None
    tags: frozenset[str] = frozenset()
    color: BookmarkColor | None = None
    priority: BookmarkPriority | None = None
    collection_id: str | None = None
    author_id: str | None = None
    updated_at: datetime | None = None

    @property
    def key(self) -> BookmarkKey:
        return BookmarkKey(self.subject_kind, self.subject_id)


def canonicalize_legacy_bookmark(bookmark: Bookmark) -> Bookmark | None:
    """Convertit la seule représentation historique ``timeline_event`` en fichier.

    Les anciens événements Timeline portaient un identifiant déterministe
    ``file_id:event_type:index``. Le préfixe est donc la seule identité fichier
    persistable à conserver. Une valeur qui ne respecte pas ce format n'est pas
    modifiée : l'appelant peut la conserver en lecture sans inventer un file_id.
    """
    if bookmark.subject_kind == "file":
        return bookmark
    if bookmark.subject_kind != "timeline_event":
        return None
    file_id, separator, _event_suffix = bookmark.subject_id.partition(":")
    if not separator or not file_id:
        return None
    return replace(bookmark, subject_kind="file", subject_id=file_id)
