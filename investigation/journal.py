"""Journal append-only consommant passivement les événements Investigation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, NewType
from uuid import uuid4

from investigation.events import DomainEvent, EventBus, EventType, InvestigationEvent
from investigation.target_ref import InvestigationTargetRef

if TYPE_CHECKING:
    from investigation.manager import InvestigationManager


InvestigationJournalEntryId = NewType("InvestigationJournalEntryId", str)


class JournalAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    MEMBERSHIP_ADDED = "membership_added"
    MEMBERSHIP_REMOVED = "membership_removed"
    RELATION_CREATED = "relation_created"
    RELATION_DELETED = "relation_deleted"


_ACTIONS_BY_EVENT_TYPE: Mapping[EventType, JournalAction] = MappingProxyType(
    {
        EventType.ITEM_CREATED: JournalAction.CREATED,
        EventType.NOTE_CREATED: JournalAction.CREATED,
        EventType.TAG_CREATED: JournalAction.CREATED,
        EventType.CASE_CREATED: JournalAction.CREATED,
        EventType.COLLECTION_CREATED: JournalAction.CREATED,
        EventType.HYPOTHESIS_CREATED: JournalAction.CREATED,
        EventType.ITEM_UPDATED: JournalAction.UPDATED,
        EventType.NOTE_UPDATED: JournalAction.UPDATED,
        EventType.TAG_UPDATED: JournalAction.UPDATED,
        EventType.CASE_UPDATED: JournalAction.UPDATED,
        EventType.COLLECTION_UPDATED: JournalAction.UPDATED,
        EventType.HYPOTHESIS_UPDATED: JournalAction.UPDATED,
        EventType.ITEM_DELETED: JournalAction.DELETED,
        EventType.NOTE_DELETED: JournalAction.DELETED,
        EventType.TAG_DELETED: JournalAction.DELETED,
        EventType.CASE_DELETED: JournalAction.DELETED,
        EventType.COLLECTION_DELETED: JournalAction.DELETED,
        EventType.HYPOTHESIS_DELETED: JournalAction.DELETED,
        EventType.MEMBERSHIP_ADDED: JournalAction.MEMBERSHIP_ADDED,
        EventType.MEMBERSHIP_REMOVED: JournalAction.MEMBERSHIP_REMOVED,
        EventType.RELATION_CREATED: JournalAction.RELATION_CREATED,
        EventType.RELATION_DELETED: JournalAction.RELATION_DELETED,
    }
)


@dataclass(frozen=True, slots=True)
class InvestigationJournalEntry:
    """Entrée d'audit immuable, construite uniquement à partir d'un événement."""

    entry_id: InvestigationJournalEntryId
    timestamp: datetime
    event_type: EventType
    target_ref: InvestigationTargetRef | None = None
    parent_ref: InvestigationTargetRef | None = None
    context: Mapping[str, str] = field(default_factory=dict)
    created_by: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entry_id, str) or not self.entry_id:
            raise ValueError("L'identifiant InvestigationJournalEntry est requis.")
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise ValueError("Une entrée de Journal doit être horodatée avec un fuseau horaire.")
        if not isinstance(self.event_type, EventType):
            raise ValueError("Le type d'événement du Journal doit être typé.")
        if self.target_ref is not None and not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("La cible du Journal doit être une référence valide.")
        if self.parent_ref is not None and not isinstance(self.parent_ref, InvestigationTargetRef):
            raise ValueError("Le parent du Journal doit être une référence valide.")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in self.context.items()):
            raise ValueError("Le contexte du Journal ne contient que des chaînes auditables.")
        if self.created_by is not None and not isinstance(self.created_by, str):
            raise ValueError("L'auteur du Journal doit être textuel.")
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))

    @property
    def action(self) -> JournalAction:
        return _ACTIONS_BY_EVENT_TYPE[self.event_type]


class JournalSubscriber:
    """Transforme les InvestigationEvent en entrées de Journal append-only."""

    def __init__(self, manager: InvestigationManager) -> None:
        self._manager = manager

    def subscribe(self, bus: EventBus) -> None:
        bus.subscribe(self)

    def unsubscribe(self, bus: EventBus) -> None:
        bus.unsubscribe(self)

    def __call__(self, event: DomainEvent) -> None:
        if not isinstance(event, InvestigationEvent) or event.event_type is EventType.BATCH_COMPLETED:
            return
        parent_ref = (
            InvestigationTargetRef(event.parent_kind, event.parent_id)
            if event.parent_kind is not None and event.parent_id is not None
            else None
        )
        context = {"entity_id": event.entity_id}
        if event.related_target_ref is not None:
            context["related_target_kind"] = event.related_target_ref.target_kind
            context["related_target_id"] = event.related_target_ref.target_id
        entry = InvestigationJournalEntry(
            entry_id=InvestigationJournalEntryId(str(uuid4())),
            timestamp=event.occurred_at,
            event_type=event.event_type,
            target_ref=event.target_ref,
            parent_ref=parent_ref,
            context=context,
            created_by=event.created_by,
        )
        self._manager._append_journal_entry(entry)
