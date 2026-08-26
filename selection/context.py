"""Contexte immuable et volontairement minimal d'une sélection applicative."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class SelectionContext:
    """Identifie un sujet sans transporter ses données métier détaillées."""

    subject_kind: str
    subject_id: str
    origin: str
    related_ids: Mapping[str, str] = field(default_factory=dict)
    navigation_hint: Mapping[str, str] = field(default_factory=dict)
    selection_id: int = 0

    def __post_init__(self) -> None:
        """Protège les petites relations contre toute mutation après publication."""
        object.__setattr__(self, "related_ids", MappingProxyType(dict(self.related_ids)))
        object.__setattr__(self, "navigation_hint", MappingProxyType(dict(self.navigation_hint)))

    def has_same_target(self, other: SelectionContext | None) -> bool:
        return bool(
            other
            and self.subject_kind == other.subject_kind
            and self.subject_id == other.subject_id
            and self.origin == other.origin
            and self.related_ids == other.related_ids
            and self.navigation_hint == other.navigation_hint
        )
