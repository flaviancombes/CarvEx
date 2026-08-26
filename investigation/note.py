"""Modèle métier autonome des notes Investigation."""

# ruff: noqa: I001, UP042
# Exceptions are limited to this legacy persisted-model module.
from __future__ import annotations

# ruff: noqa: UP042
# L'enum conserve la représentation publique historique du format de note.

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import NewType

from investigation.target_ref import InvestigationTargetRef

InvestigationNoteId = NewType("InvestigationNoteId", str)


class InvestigationNoteFormat(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    PLAIN_TEXT = "plain_text"
    MARKDOWN = "markdown"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvestigationNote:
    """Documentation indépendante d'une cible Investigation facultative."""

    note_id: InvestigationNoteId
    target_ref: InvestigationTargetRef | None
    body: str
    format: InvestigationNoteFormat = InvestigationNoteFormat.PLAIN_TEXT
    author: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not isinstance(self.note_id, str) or not self.note_id:
            raise ValueError("L'identifiant InvestigationNote est requis.")
        if self.target_ref is not None and not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("La cible d'une note Investigation doit être une référence valide.")
        if not isinstance(self.body, str) or not self.body.strip():
            raise ValueError("Le contenu d'une note Investigation est requis.")
        if not isinstance(self.format, InvestigationNoteFormat):
            raise ValueError("Le format d'une note Investigation doit être typé.")
        if self.author is not None and not isinstance(self.author, str):
            raise ValueError("L'auteur d'une note Investigation doit être textuel.")
        if not isinstance(self.created_at, datetime) or not isinstance(self.updated_at, datetime):
            raise ValueError("Les dates InvestigationNote doivent être valides.")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Les dates InvestigationNote doivent inclure un fuseau horaire.")
        if self.updated_at < self.created_at:
            raise ValueError("La date de mise à jour ne peut pas précéder la création.")
