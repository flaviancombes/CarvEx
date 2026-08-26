"""Contrat de résolution unique des identités transversales."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from bookmarks.model import Bookmark, BookmarkKey
from investigation.item import InvestigationItem, InvestigationItemId
from investigation.target_ref import InvestigationTargetRef
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.resolver import FileSelectionRegistry
from timeline.event import TimelineEvent
from timeline.source import FILE_CREATED, FILESYSTEM


def _record() -> dict[str, str]:
    return {"file_id": str(uuid4()), "name": "evidence.jpg"}


def _event(record: dict[str, str]) -> TimelineEvent:
    return TimelineEvent(
        FILE_CREATED,
        datetime(2025, 1, 1, tzinfo=UTC),
        FILESYSTEM,
        event_id="event-1",
        file_record=record,
    )


def test_all_file_representations_resolve_to_the_same_file_identity():
    record = _record()
    event = _event(record)
    item = InvestigationItem(InvestigationItemId(str(uuid4())), "file", record["file_id"], title="Preuve")
    files = FileSelectionRegistry()
    files.set_records((record,))
    resolver = CanonicalEntityResolver(files)
    resolver.set_timeline_event_lookup(lambda identifier: event if identifier == event.event_id else None)
    resolver.set_investigation_item_lookup(lambda identifier: item if identifier == item.item_id else None)

    entities = (
        record,
        event,
        Bookmark("file", record["file_id"], datetime.now(UTC)),
        Bookmark("timeline_event", event.event_id, datetime.now(UTC)),
        item,
        InvestigationTargetRef("file", record["file_id"]),
        InvestigationTargetRef("timeline_event", event.event_id),
        InvestigationTargetRef("item", str(item.item_id)),
    )

    assert {resolver.file_id_for(entity) for entity in entities} == {record["file_id"]}
    assert {resolver.bookmark_key_for(entity) for entity in entities} == {BookmarkKey("file", record["file_id"])}


def test_unknown_reference_is_not_silently_promoted_to_a_file():
    resolver = CanonicalEntityResolver()

    resolved = resolver.resolve(InvestigationTargetRef("timeline_event", "not-loaded"))

    assert resolved is None


def test_invalid_file_identifier_is_not_promoted_to_a_canonical_file():
    resolver = CanonicalEntityResolver()

    assert resolver.resolve(InvestigationTargetRef("file", "display-name.jpg")) is None
