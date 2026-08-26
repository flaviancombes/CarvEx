"""Validation Qt du glisser-déposer d'organisation Investigation."""

from __future__ import annotations

from models.investigation_tree_model import InvestigationTreeEntry


class InvestigationDragDropPolicy:
    """Déclare les associations valides sans exécuter de commande métier."""

    @staticmethod
    def accepts(source: InvestigationTreeEntry | None, target: InvestigationTreeEntry | None) -> bool:
        if source is None or target is None:
            return False
        if source.subject_kind not in {"item", "collection"}:
            return False
        if target.subject_kind not in {"case", "collection"}:
            return False
        return source.subject_kind != "collection" or target.subject_kind == "case"
