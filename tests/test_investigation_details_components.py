from __future__ import annotations

from types import SimpleNamespace

from investigation.relation import InvestigationRelationType
from investigation.target_ref import InvestigationTargetRef
from selection.canonical_entity_resolver import CanonicalEntity
from selection.context import SelectionContext
from ui.investigation_details_components import (
    InvestigationPreviewBridge,
    InvestigationRelationRenderer,
    InvestigationTargetRenderer,
)


def test_target_renderer_uses_public_service_lookup_for_a_file_evidence():
    evidence = SimpleNamespace(title="Photo de preuve")

    class Service:
        def find_item_by_subject(self, kind, identifier):
            assert (kind, identifier) == ("file", "file-1")
            return evidence

    renderer = InvestigationTargetRenderer(Service())

    assert renderer.label(InvestigationTargetRef("file", "file-1")) == "Photo de preuve"
    assert renderer.with_icon(InvestigationTargetRef("file", "file-1")).endswith("Photo de preuve")


def test_relation_renderer_centralizes_the_existing_relation_vocabulary():
    assert InvestigationRelationRenderer.phrase(InvestigationRelationType.CONFIRMS) == "soutient"
    assert InvestigationRelationRenderer.phrase(InvestigationRelationType.DUPLICATES) == "duplique"


def test_preview_bridge_uses_the_explicit_details_panel_contract():
    class Resolver:
        def resolve(self, _value):
            return CanonicalEntity("file", "file-1")

    class Panel:
        def __init__(self):
            self.context = None
            self.extension = None

        def populate_file_context(self, context):
            self.context = context
            return True

        def current_file_title(self):
            return "original.jpg"

        def show_file_extension_widget(self, widget):
            self.extension = widget

    class Widget:
        def __init__(self):
            self.name = None

        def set_file_presentation_name(self, name):
            self.name = name

    panel = Panel()
    widget = Widget()
    bridge = InvestigationPreviewBridge(Resolver())

    assert bridge.present(panel, object(), SelectionContext("item", "item-1", "test"), widget)
    assert panel.context == SelectionContext("file", "file-1", "investigation_evidence")
    assert panel.extension is widget
    assert widget.name == "original.jpg"


def test_preview_bridge_leaves_non_item_context_to_the_provider():
    class Resolver:
        def resolve(self, _value):
            return CanonicalEntity("file", "file-1")

    bridge = InvestigationPreviewBridge(Resolver())

    assert not bridge.present(object(), object(), SelectionContext("case", "case-1", "test"), object())
