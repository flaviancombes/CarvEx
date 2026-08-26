"""Agrégat racine des affaires Investigation et memberships associés."""

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

InvestigationCaseId = NewType("InvestigationCaseId", str)
CaseMembershipId = NewType("CaseMembershipId", str)


class CaseStatus(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    CLOSED = "closed"
    ARCHIVED = "archived"


class CasePriority(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATION = "information"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvestigationCase:
    """Enquête logique sans copie des objets Investigation qu'elle organise."""

    case_id: InvestigationCaseId
    title: str
    description: str | None = None
    status: CaseStatus = CaseStatus.OPEN
    priority: CasePriority = CasePriority.INFORMATION
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    created_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id:
            raise ValueError("L'identifiant InvestigationCase est requis.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("Le titre d'une Case est requis.")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("La description d'une Case doit être textuelle.")
        if not isinstance(self.status, CaseStatus) or not isinstance(self.priority, CasePriority):
            raise ValueError("Le statut et la priorité d'une Case doivent être typés.")
        if not isinstance(self.created_at, datetime) or not isinstance(self.updated_at, datetime):
            raise ValueError("Les dates InvestigationCase doivent être valides.")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Les dates InvestigationCase doivent inclure un fuseau horaire.")
        if self.updated_at < self.created_at:
            raise ValueError("La date de mise à jour ne peut pas précéder la création.")


@dataclass(frozen=True, slots=True)
class CaseMembership:
    """Association indépendante entre une Case et une référence métier légère."""

    membership_id: CaseMembershipId
    case_id: InvestigationCaseId
    target_ref: InvestigationTargetRef
    added_at: datetime = field(default_factory=_now)
    added_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.membership_id, str) or not self.membership_id:
            raise ValueError("L'identifiant CaseMembership est requis.")
        if not isinstance(self.case_id, str) or not self.case_id:
            raise ValueError("Un membership doit référencer une Case valide.")
        if not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("Un membership doit référencer une cible valide.")
        if not isinstance(self.added_at, datetime) or self.added_at.tzinfo is None:
            raise ValueError("La date d'ajout doit inclure un fuseau horaire.")
        if self.added_by is not None and not isinstance(self.added_by, str):
            raise ValueError("L'auteur d'un membership doit être textuel.")
