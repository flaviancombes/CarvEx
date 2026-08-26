"""Primitives de résultat réutilisables pour les commandes de masse.

Ce module ne connaît ni Qt, ni Investigation, ni un backend de persistance.
Les services de domaine l'emploient pour exposer le résultat d'une commande
atomique sans publier une notification par élément traité.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import uuid4

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BatchOperationResult(Generic[T]):
    """Résultat immuable d'une unique commande métier de masse.

    ``applied`` contient les objets effectivement créés ou associés. Les
    entrées dédupliquées ou déjà présentes sont signalées dans ``skipped``.
    """

    requested_count: int
    applied: tuple[T, ...]
    skipped: tuple[T, ...] = ()
    operation_id: str = ""

    def __post_init__(self) -> None:
        if self.requested_count < 0:
            raise ValueError("Le nombre d'éléments demandés ne peut pas être négatif.")
        if not self.operation_id:
            object.__setattr__(self, "operation_id", str(uuid4()))

    @property
    def applied_count(self) -> int:
        return len(self.applied)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)
