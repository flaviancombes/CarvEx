"""Tests de la phase 9 : événements métier Investigation."""

from __future__ import annotations

import gc
import weakref

from investigation.events import EventBus, EventType, InvestigationEvent
from investigation.module import InvestigationProjectModule
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry


def _event(event_type: EventType, entity_id: str) -> InvestigationEvent:
    return InvestigationEvent(event_type=event_type, entity_id=entity_id)


def _service() -> InvestigationService:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project = ProjectManager(modules).create_project(ProjectMetadata("Evénements Investigation"))
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return service


def test_event_bus_publishes_to_subscribers_in_subscription_order():
    bus = EventBus()
    received: list[str] = []
    bus.subscribe(lambda _event: received.append("first"))
    bus.subscribe(lambda _event: received.append("second"), frozenset({EventType.ITEM_CREATED}))

    bus.publish(_event(EventType.ITEM_CREATED, "item-1"))

    assert received == ["first", "second"]


def test_event_bus_filters_and_delivers_multiple_events():
    bus = EventBus()
    received: list[EventType] = []
    bus.subscribe(lambda event: received.append(event.event_type), frozenset({EventType.TAG_CREATED}))

    bus.publish(_event(EventType.ITEM_CREATED, "item-1"))
    bus.publish(_event(EventType.TAG_CREATED, "tag-1"))
    bus.publish(_event(EventType.TAG_CREATED, "tag-2"))

    assert received == [EventType.TAG_CREATED, EventType.TAG_CREATED]


def test_event_bus_unsubscribe_releases_subscriber_reference():
    bus = EventBus()

    class Subscriber:
        def __call__(self, _event) -> None:
            pass

    subscriber = Subscriber()
    reference = weakref.ref(subscriber)
    bus.subscribe(subscriber)
    bus.unsubscribe(subscriber)
    del subscriber
    gc.collect()

    assert bus.subscriber_count == 0
    assert reference() is None


def test_event_bus_unsubscribes_a_bound_method_retrieved_again():
    bus = EventBus()
    received: list[str] = []

    class Subscriber:
        def receive(self, _event) -> None:
            received.append("called")

    subscriber = Subscriber()
    bus.subscribe(subscriber.receive)
    bus.unsubscribe(subscriber.receive)
    bus.publish(_event(EventType.ITEM_CREATED, "item-1"))

    assert bus.subscriber_count == 0
    assert received == []


def test_event_bus_isolates_subscriber_exceptions_and_keeps_delivery_order(caplog):
    bus = EventBus()
    received: list[str] = []

    def failing_subscriber(_event) -> None:
        received.append("failing")
        raise RuntimeError("subscriber failure")

    bus.subscribe(lambda _event: received.append("first"))
    bus.subscribe(failing_subscriber)
    bus.subscribe(lambda _event: received.append("last"))

    bus.publish(_event(EventType.ITEM_CREATED, "item-1"))

    assert received == ["first", "failing", "last"]
    assert "subscriber failure" in caplog.text


def test_failing_optional_subscriber_does_not_prevent_journal_entry():
    service = _service()
    bus = service.event_bus
    assert bus is not None

    def failing_subscriber(_event) -> None:
        raise RuntimeError("optional integration failed")

    bus.subscribe(failing_subscriber)

    item = service.create_item("file", "file-1")

    entries = service.list_entries()
    assert len(entries) == 1
    assert entries[0].event_type is EventType.ITEM_CREATED
    assert entries[0].context == {"entity_id": str(item.item_id)}


def test_investigation_service_publishes_compact_domain_events_after_changes():
    service = _service()
    bus = service.event_bus
    assert bus is not None
    received: list[InvestigationEvent] = []
    bus.subscribe(received.append)

    item = service.create_item("file", "file-1")
    collection = service.create_collection("A analyser")
    target = InvestigationTargetRef("file", "file-1")
    membership = service.add_to_collection(collection.collection_id, target)
    service.remove_from_collection(collection.collection_id, target)
    service.delete_item(item.item_id)

    assert [event.event_type for event in received] == [
        EventType.ITEM_CREATED,
        EventType.COLLECTION_CREATED,
        EventType.MEMBERSHIP_ADDED,
        EventType.MEMBERSHIP_REMOVED,
        EventType.ITEM_DELETED,
    ]
    assert received[0].target_ref == target
    assert received[2].entity_id == str(membership.membership_id)
    assert received[2].parent_kind == "collection"
    assert received[2].parent_id == str(collection.collection_id)
