"""Modèle métier minimal d'un élément Investigation."""

# ruff: noqa: I001, UP042
# Exceptions are limited to this legacy persisted-model module.
from __future__ import annotations

# ruff: noqa: UP042
# Les enums `str, Enum` conservent la représentation publique des projets existants.

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import NewType

InvestigationItemId = NewType("InvestigationItemId", str)


class InvestigationPriority(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATION = "information"


class InvestigationStatus(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    NEW = "new"
    TO_ANALYZE = "to_analyze"
    IN_PROGRESS = "in_progress"
    VALIDATED = "validated"
    IGNORED = "ignored"
    REPORTED = "reported"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class InvestigationItem:
    """Annotation d'enquête légère, jamais une copie du sujet référencé."""

    item_id: InvestigationItemId
    subject_kind: str
    subject_id: str
    title: str | None = None
    summary: str | None = None
    priority: InvestigationPriority = InvestigationPriority.INFORMATION
    status: InvestigationStatus = InvestigationStatus.NEW
    # Les projets antérieurs à l'introduction de cette donnée peuvent ne pas
    # posséder la clé persistée. ``None`` conserve alors honnêtement cette
    # absence, sans fabriquer une date lors de leur ouverture.
    created_at: datetime | None = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    created_by: str | None = None
    updated_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id:
            raise ValueError("L'identifiant InvestigationItem est requis.")
        if not isinstance(self.subject_kind, str) or not isinstance(self.subject_id, str):
            raise ValueError("La référence d'un InvestigationItem doit être textuelle.")
        if not self.subject_kind.strip() or not self.subject_id.strip():
            raise ValueError("Un InvestigationItem doit référencer un sujet valide.")
        if not isinstance(self.priority, InvestigationPriority) or not isinstance(self.status, InvestigationStatus):
            raise ValueError("La priorité et le statut InvestigationItem doivent être typés.")
        if self.created_at is not None and not isinstance(self.created_at, datetime):
            raise ValueError("La date de création InvestigationItem doit être valide.")
        if not isinstance(self.updated_at, datetime):
            raise ValueError("Les dates InvestigationItem doivent être valides.")
        if self.created_at is not None and self.created_at.tzinfo is None:
            raise ValueError("Les dates InvestigationItem doivent inclure un fuseau horaire.")
        if self.updated_at.tzinfo is None:
            raise ValueError("Les dates InvestigationItem doivent inclure un fuseau horaire.")
        if self.created_at is not None and self.updated_at < self.created_at:
            raise ValueError("La date de mise à jour ne peut pas précéder la création.")

    @property
    def subject_ref(self) -> tuple[str, str]:
        """Clé légère, stable et indépendante des modules fournisseurs."""
        return self.subject_kind, self.subject_id
