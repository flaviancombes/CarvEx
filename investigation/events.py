"""Evénements métier synchrones et indépendants de Qt pour Investigation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from investigation.target_ref import InvestigationTargetRef

LOGGER = logging.getLogger(__name__)


class EventType(StrEnum):
    ITEM_CREATED = "item_created"
    NOTE_CREATED = "note_created"
    TAG_CREATED = "tag_created"
    CASE_CREATED = "case_created"
    COLLECTION_CREATED = "collection_created"
    HYPOTHESIS_CREATED = "hypothesis_created"
    ITEM_UPDATED = "item_updated"
    NOTE_UPDATED = "note_updated"
    TAG_UPDATED = "tag_updated"
    CASE_UPDATED = "case_updated"
    COLLECTION_UPDATED = "collection_updated"
    HYPOTHESIS_UPDATED = "hypothesis_updated"
    ITEM_DELETED = "item_deleted"
    NOTE_DELETED = "note_deleted"
    TAG_DELETED = "tag_deleted"
    CASE_DELETED = "case_deleted"
    COLLECTION_DELETED = "collection_deleted"
    HYPOTHESIS_DELETED = "hypothesis_deleted"
    MEMBERSHIP_ADDED = "membership_added"
    MEMBERSHIP_REMOVED = "membership_removed"
    RELATION_CREATED = "relation_created"
    RELATION_DELETED = "relation_deleted"
    BATCH_COMPLETED = "batch_completed"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base immuable de tout événement métier CarvEx."""

    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("L'identifiant d'un événement est requis.")
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None:
            raise ValueError("Un événement doit être horodaté avec un fuseau horaire.")


@dataclass(frozen=True, slots=True)
class InvestigationEvent(DomainEvent):
    """Fait Investigation : identifiants et références, jamais des objets copiés."""

    event_type: EventType = EventType.ITEM_CREATED
    entity_id: str = ""
    target_ref: InvestigationTargetRef | None = None
    related_target_ref: InvestigationTargetRef | None = None
    parent_kind: str | None = None
    parent_id: str | None = None
    created_by: str | None = None

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if not isinstance(self.event_type, EventType):
            raise ValueError("Le type d'un événement Investigation doit être typé.")
        if not isinstance(self.entity_id, str) or not self.entity_id:
            raise ValueError("L'entité concernée par un événement est requise.")
        if self.target_ref is not None and not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("La cible d'un événement doit être une référence valide.")
        if self.related_target_ref is not None and not isinstance(self.related_target_ref, InvestigationTargetRef):
            raise ValueError("La cible associée doit être une référence valide.")
        if (self.parent_kind is None) != (self.parent_id is None):
            raise ValueError("Le contexte parent doit contenir un type et un identifiant.")
        if self.parent_kind is not None and (
            not self.parent_kind.strip() or not self.parent_id or not self.parent_id.strip()
        ):
            raise ValueError("Le contexte parent d'un événement est invalide.")
        if self.created_by is not None and not isinstance(self.created_by, str):
            raise ValueError("L'auteur d'un événement doit être textuel.")


class EventPublisher(Protocol):
    def publish(self, event: DomainEvent) -> None: ...


class EventSubscriber(Protocol):
    def __call__(self, event: DomainEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class _Subscription:
    subscriber: EventSubscriber
    event_types: frozenset[EventType] | None
    key: tuple[str, int, int]


def _subscriber_key(subscriber: EventSubscriber) -> tuple[str, int, int]:
    """Identifie durablement un callable, y compris une méthode liée.

    Chaque accès à ``instance.method`` crée un nouvel objet méthode. Son
    identité Python ne peut donc pas être utilisée pour le désabonnement.
    Le couple instance/fonction reste, lui, stable sur tout son cycle de vie.
    """
    instance = getattr(subscriber, "__self__", None)
    function = getattr(subscriber, "__func__", None)
    if instance is not None and function is not None:
        return "bound_method", id(instance), id(function)
    return "callable", id(subscriber), 0


class EventBus(EventPublisher):
    """Diffuse synchroniquement les événements dans l'ordre d'abonnement.

    Politique d'erreur : une exception d'abonné est journalisée puis isolée.
    La diffusion continue vers les abonnés suivants et l'exception n'est pas
    propagée à la commande métier déjà appliquée. Cette règle empêche un
    consommateur UI ou optionnel de bloquer le Journal ou le domaine.
    """

    def __init__(self) -> None:
        self._subscriptions: list[_Subscription] = []

    def subscribe(
        self,
        subscriber: EventSubscriber,
        event_types: frozenset[EventType] | None = None,
    ) -> None:
        if not callable(subscriber):
            raise TypeError("Un abonné d'événements doit être appelable.")
        if event_types is not None and not all(isinstance(event_type, EventType) for event_type in event_types):
            raise ValueError("Les filtres d'événements doivent être typés.")
        subscription = _Subscription(subscriber, event_types, _subscriber_key(subscriber))
        if not any(
            entry.key == subscription.key and entry.event_types == subscription.event_types
            for entry in self._subscriptions
        ):
            self._subscriptions.append(subscription)

    def unsubscribe(self, subscriber: EventSubscriber) -> None:
        """Supprime toute référence au subscriber et évite sa rétention mémoire."""
        key = _subscriber_key(subscriber)
        self._subscriptions = [entry for entry in self._subscriptions if entry.key != key]

    def publish(self, event: DomainEvent) -> None:
        if not isinstance(event, DomainEvent):
            raise TypeError("Seuls les DomainEvent peuvent être publiés.")
        event_type = event.event_type if isinstance(event, InvestigationEvent) else None
        for subscription in tuple(self._subscriptions):
            if subscription.event_types is None or event_type in subscription.event_types:
                try:
                    subscription.subscriber(event)
                except Exception:
                    LOGGER.exception(
                        "Subscriber Investigation en erreur pour l'événement %s : %r",
                        event.event_id,
                        subscription.subscriber,
                    )

    @property
    def subscriber_count(self) -> int:
        """Indicateur de test et de diagnostic ; ne fait pas partie de la persistance."""
        return len(self._subscriptions)
