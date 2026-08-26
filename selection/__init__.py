"""Sélection applicative légère, partagée par toutes les vues CarvEx."""

from selection.canonical_entity_resolver import CanonicalEntity, CanonicalEntityResolver
from selection.context import SelectionContext
from selection.manager import SelectionManager
from selection.resolver import FileSelectionRegistry, FileSelectionResolver

__all__ = (
    "CanonicalEntity",
    "CanonicalEntityResolver",
    "SelectionContext",
    "SelectionManager",
    "FileSelectionRegistry",
    "FileSelectionResolver",
)
