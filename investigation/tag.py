"""Modèles métier du catalogue global de tags Investigation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NewType

from investigation.target_ref import InvestigationTargetRef

InvestigationTagId = NewType("InvestigationTagId", str)
TagAssignmentId = NewType("TagAssignmentId", str)


def normalize_tag_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("Le nom d'un tag doit être textuel.")
    normalized = " ".join(name.split()).casefold()
    if not normalized:
        raise ValueError("Le nom d'un tag est requis.")
    return normalized


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvestigationTag:
    """Entrée normalisée du catalogue de tags d'un projet."""

    tag_id: InvestigationTagId
    normalized_name: str
    display_name: str
    color: str | None = None
    description: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not isinstance(self.tag_id, str) or not self.tag_id:
            raise ValueError("L'identifiant InvestigationTag est requis.")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("Le nom affiché d'un tag est requis.")
        if self.normalized_name != normalize_tag_name(self.display_name):
            raise ValueError("Le nom normalisé d'un tag doit correspondre au nom affiché.")
        if self.color is not None and not isinstance(self.color, str):
            raise ValueError("La couleur d'un tag doit être textuelle.")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("La description d'un tag doit être textuelle.")
        if not isinstance(self.created_at, datetime) or not isinstance(self.updated_at, datetime):
            raise ValueError("Les dates InvestigationTag doivent être valides.")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Les dates InvestigationTag doivent inclure un fuseau horaire.")
        if self.updated_at < self.created_at:
            raise ValueError("La date de mise à jour ne peut pas précéder la création.")


@dataclass(frozen=True, slots=True)
class TagAssignment:
    """Association primaire entre un tag et une cible, sans copie de cible."""

    assignment_id: TagAssignmentId
    tag_id: InvestigationTagId
    target_ref: InvestigationTargetRef
    assigned_at: datetime = field(default_factory=_now)
    assigned_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.assignment_id, str) or not self.assignment_id:
            raise ValueError("L'identifiant TagAssignment est requis.")
        if not isinstance(self.tag_id, str) or not self.tag_id:
            raise ValueError("Une assignation doit référencer un tag valide.")
        if not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("Une assignation doit référencer une cible valide.")
        if not isinstance(self.assigned_at, datetime) or self.assigned_at.tzinfo is None:
            raise ValueError("La date d'assignation doit inclure un fuseau horaire.")
        if self.assigned_by is not None and not isinstance(self.assigned_by, str):
            raise ValueError("L'auteur d'une assignation doit être textuel.")
