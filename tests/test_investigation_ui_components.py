"""Non-régressions des composants extraits de la vue Investigation."""

from __future__ import annotations

from models.investigation_tree_model import InvestigationTreeEntry
from ui.investigation_drag_drop import InvestigationDragDropPolicy


def test_drag_drop_policy_preserves_valid_investigation_memberships():
    item = InvestigationTreeEntry("item", "item-1", "Preuve")
    collection = InvestigationTreeEntry("collection", "collection-1", "Collection")
    case = InvestigationTreeEntry("case", "case-1", "Case")

    assert InvestigationDragDropPolicy.accepts(item, case)
    assert InvestigationDragDropPolicy.accepts(item, collection)
    assert InvestigationDragDropPolicy.accepts(collection, case)
    assert not InvestigationDragDropPolicy.accepts(collection, collection)
    assert not InvestigationDragDropPolicy.accepts(case, collection)
