"""Structures de sortie stables pour les artefacts détectés."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Artifact:
    """Une interprétation DFIR affichable et filtrable."""

    identifier: str
    label: str
    filter_ids: tuple[str, ...] = ()
    severity: str = "info"

    def matches(self, filter_id: str) -> bool:
        """Indique si l'artefact appartient au filtre demandé."""
        return filter_id in self.filter_ids
