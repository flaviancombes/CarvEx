"""Modèles métier des hypothèses Investigation et de leurs preuves liées."""

# ruff: noqa: I001, UP042
# Exceptions are limited to this legacy persisted-model module.
from __future__ import annotations

# ruff: noqa: UP042
# Les enums `str, Enum` conservent la représentation publique des projets existants.

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import NewType

from investigation.target_ref import InvestigationTargetRef

InvestigationHypothesisId = NewType("InvestigationHypothesisId", str)
HypothesisMembershipId = NewType("HypothesisMembershipId", str)


class HypothesisStatus(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    CONCLUDED = "concluded"
    ARCHIVED = "archived"


class HypothesisConfidence(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class HypothesisRole(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    OBSERVATION = "observation"
    SOURCE = "source"
    RESULT = "result"
    REFERENCE = "reference"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvestigationHypothesis:
    """Raisonnement d'investigation, distinct des objets utilisés pour l'étayer."""

    hypothesis_id: InvestigationHypothesisId
    title: str
    description: str | None = None
    status: HypothesisStatus = HypothesisStatus.DRAFT
    confidence: HypothesisConfidence = HypothesisConfidence.UNKNOWN
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    created_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis_id, str) or not self.hypothesis_id:
            raise ValueError("L'identifiant InvestigationHypothesis est requis.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Le titre d'une Hypothèse est requis.")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("La description d'une Hypothèse doit être textuelle.")
        if not isinstance(self.status, HypothesisStatus) or not isinstance(self.confidence, HypothesisConfidence):
            raise ValueError("Le statut et la confiance d'une Hypothèse doivent être typés.")
        if self.created_by is not None and not isinstance(self.created_by, str):
            raise ValueError("L'auteur d'une Hypothèse doit être textuel.")
        if not isinstance(self.created_at, datetime) or not isinstance(self.updated_at, datetime):
            raise ValueError("Les dates InvestigationHypothesis doivent être valides.")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Les dates InvestigationHypothesis doivent inclure un fuseau horaire.")
        if self.updated_at < self.created_at:
            raise ValueError("La date de mise à jour ne peut pas précéder la création.")


@dataclass(frozen=True, slots=True)
class HypothesisMembership:
    """Rôle d'une cible légère dans un raisonnement d'investigation."""

    membership_id: HypothesisMembershipId
    hypothesis_id: InvestigationHypothesisId
    target_ref: InvestigationTargetRef
    role: HypothesisRole
    added_at: datetime = field(default_factory=_now)
    added_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.membership_id, str) or not self.membership_id:
            raise ValueError("L'identifiant HypothesisMembership est requis.")
        if not isinstance(self.hypothesis_id, str) or not self.hypothesis_id:
            raise ValueError("Un membership doit référencer une Hypothèse valide.")
        if not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("Un membership doit référencer une cible valide.")
        if not isinstance(self.role, HypothesisRole):
            raise ValueError("Le rôle d'un membership d'Hypothèse doit être typé.")
        if not isinstance(self.added_at, datetime) or self.added_at.tzinfo is None:
            raise ValueError("La date d'ajout doit inclure un fuseau horaire.")
        if self.added_by is not None and not isinstance(self.added_by, str):
            raise ValueError("L'auteur d'un membership doit être textuel.")
