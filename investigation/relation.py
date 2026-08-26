"""Modèle métier des relations Investigation."""

# ruff: noqa: I001, UP042
# Exceptions are limited to this legacy persisted-model module.
from __future__ import annotations

# ruff: noqa: UP042
# L'enum conserve la représentation publique historique des types de relation.

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import NewType

from investigation.target_ref import InvestigationTargetRef

InvestigationRelationId = NewType("InvestigationRelationId", str)


class InvestigationRelationType(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    RELATED_TO = "related_to"
    CONFIRMS = "confirms"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"
    DUPLICATES = "duplicates"
    REFERENCES = "references"


@dataclass(frozen=True, slots=True)
class InvestigationRelationSemantics:
    symmetric: bool = False
    allows_self_reference: bool = False


RELATION_SEMANTICS: Mapping[InvestigationRelationType, InvestigationRelationSemantics] = {
    relation_type: InvestigationRelationSemantics() for relation_type in InvestigationRelationType
} | {
    InvestigationRelationType.DUPLICATES: InvestigationRelationSemantics(symmetric=True),
}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvestigationRelation:
    """Lien typé entre deux références, sans copie des sujets désignés."""

    relation_id: InvestigationRelationId
    source_target: InvestigationTargetRef
    destination_target: InvestigationTargetRef
    relation_type: InvestigationRelationType
    comment: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    created_by: str | None = None
    updated_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.relation_id, str) or not self.relation_id:
            raise ValueError("L'identifiant InvestigationRelation est requis.")
        if not isinstance(self.source_target, InvestigationTargetRef) or not isinstance(
            self.destination_target, InvestigationTargetRef
        ):
            raise ValueError("Une relation doit référencer exactement deux cibles valides.")
        if not isinstance(self.relation_type, InvestigationRelationType):
            raise ValueError("Le type de relation Investigation doit être typé.")
        if not isinstance(self.created_at, datetime) or not isinstance(self.updated_at, datetime):
            raise ValueError("Les dates InvestigationRelation doivent être valides.")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Les dates InvestigationRelation doivent inclure un fuseau horaire.")
        if self.updated_at < self.created_at:
            raise ValueError("La date de mise à jour ne peut pas précéder la création.")

    @property
    def semantics(self) -> InvestigationRelationSemantics:
        return RELATION_SEMANTICS[self.relation_type]

    @property
    def signature(self) -> tuple[InvestigationRelationType, InvestigationTargetRef, InvestigationTargetRef]:
        """Clé de déduplication, après normalisation éventuelle par le manager."""
        return self.relation_type, self.source_target, self.destination_target
