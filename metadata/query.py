"""Façade de lecture immutable pour les requêtes sur ``MetadataIndex``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from metadata.index import MetadataIndex


@dataclass(frozen=True, slots=True)
class MetadataPredicate:
    """Critère exact ou de présence d'un champ persisté."""

    identifier: str
    value: object | None = None
    present: bool = True

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("Un identifiant de métadonnée est obligatoire.")


@dataclass(frozen=True, slots=True)
class MetadataFilter:
    """Groupe réutilisable de prédicats combinés par conjonction."""

    predicates: tuple[MetadataPredicate, ...] = ()

    def execute(self, index: MetadataIndex, candidates: Iterable[str] | None = None) -> frozenset[str]:
        return index.query(self.predicates, candidates)


@dataclass(frozen=True, slots=True)
class MetadataQuery:
    """Conjonction de filtres et recherche texte, sans provider ni disque."""

    predicates: tuple[MetadataPredicate, ...] = ()
    text: str = ""
    filters: tuple[MetadataFilter, ...] = ()

    def execute(self, index: MetadataIndex, candidates: Iterable[str] | None = None) -> frozenset[str]:
        matches = index.query(self.predicates, candidates)
        for metadata_filter in self.filters:
            matches = frozenset(matches.intersection(metadata_filter.execute(index, matches)))
            if not matches:
                return matches
        if not self.text.strip():
            return matches
        return frozenset(matches.intersection(index.search(self.text)))
