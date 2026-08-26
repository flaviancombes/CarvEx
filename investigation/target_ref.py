"""Référence métier légère et réutilisable entre modules CarvEx."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InvestigationTargetRef:
    """Identifie un sujet sans importer ni copier son objet métier source."""

    target_kind: str
    target_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.target_kind, str) or not isinstance(self.target_id, str):
            raise ValueError("Une référence Investigation doit être textuelle.")
        if not self.target_kind.strip() or not self.target_id.strip():
            raise ValueError("Une référence Investigation doit identifier une cible valide.")

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.target_kind, self.target_id
