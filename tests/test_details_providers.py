from __future__ import annotations

from selection.context import SelectionContext
from ui.details_providers import DetailsProviderRegistry, FileDetailsProvider


def test_details_provider_registry_uses_the_most_specific_latest_provider():
    calls: list[str] = []

    class GenericProvider:
        def supports(self, _context) -> bool:
            return True

        def populate(self, _panel, _context) -> None:
            calls.append("generic")

    class FileProvider:
        def supports(self, context) -> bool:
            return context.subject_kind == "file"

        def populate(self, _panel, _context) -> None:
            calls.append("file")

    registry = DetailsProviderRegistry()
    registry.register(GenericProvider())
    registry.register(FileProvider())

    assert registry.populate(object(), SelectionContext("file", "file-1", "test"))
    assert calls == ["file"]


def test_details_provider_registry_leaves_unknown_selection_unhandled():
    registry = DetailsProviderRegistry()

    assert not registry.populate(object(), SelectionContext("unknown", "id", "test"))


def test_file_details_provider_preserves_existing_file_resolution_contract():
    record = {"file_id": "file-1", "name": "photo.jpg"}

    class Resolver:
        def resolve_file(self, context):
            return record if context.related_ids.get("file_id") == "file-1" else None

    class Panel:
        received = None

        def set_file(self, file_record) -> None:
            self.received = file_record

    panel = Panel()
    provider = FileDetailsProvider(Resolver())
    context = SelectionContext("timeline_event", "event-1", "timeline", related_ids={"file_id": "file-1"})

    assert provider.supports(context)
    provider.populate(panel, context)
    assert panel.received is record
