"""Modèles métier des collections Investigation et de leurs memberships."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NewType

from investigation.target_ref import InvestigationTargetRef

InvestigationCollectionId = NewType("InvestigationCollectionId", str)
CollectionMembershipId = NewType("CollectionMembershipId", str)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvestigationCollection:
    """Regroupement logique sans copie des objets métier qu'il organise."""

    collection_id: InvestigationCollectionId
    title: str
    description: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    created_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.collection_id, str) or not self.collection_id:
            raise ValueError("L'identifiant InvestigationCollection est requis.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Le titre d'une Collection est requis.")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("La description d'une Collection doit être textuelle.")
        if self.created_by is not None and not isinstance(self.created_by, str):
            raise ValueError("L'auteur d'une Collection doit être textuel.")
        if not isinstance(self.created_at, datetime) or not isinstance(self.updated_at, datetime):
            raise ValueError("Les dates InvestigationCollection doivent être valides.")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Les dates InvestigationCollection doivent inclure un fuseau horaire.")
        if self.updated_at < self.created_at:
            raise ValueError("La date de mise à jour ne peut pas précéder la création.")


@dataclass(frozen=True, slots=True)
class CollectionMembership:
    """Association indépendante entre une Collection et une cible légère."""

    membership_id: CollectionMembershipId
    collection_id: InvestigationCollectionId
    target_ref: InvestigationTargetRef
    added_at: datetime = field(default_factory=_now)
    added_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.membership_id, str) or not self.membership_id:
            raise ValueError("L'identifiant CollectionMembership est requis.")
        if not isinstance(self.collection_id, str) or not self.collection_id:
            raise ValueError("Un membership doit référencer une Collection valide.")
        if not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("Un membership doit référencer une cible valide.")
        if not isinstance(self.added_at, datetime) or self.added_at.tzinfo is None:
            raise ValueError("La date d'ajout doit inclure un fuseau horaire.")
        if self.added_by is not None and not isinstance(self.added_by, str):
            raise ValueError("L'auteur d'un membership doit être textuel.")
