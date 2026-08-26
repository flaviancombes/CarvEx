"""Prédicats de filtre composables pour les consommateurs de timeline."""

from __future__ import annotations

from collections.abc import Iterable

from timeline.event import TimelineEvent


def filter_events(
    events: Iterable[TimelineEvent], search: str = "", category: str = "", event_type: str = ""
) -> tuple[TimelineEvent, ...]:
    needle = search.casefold().strip()
    return tuple(event for event in events if matches_normalized(event, needle, category, event_type))


def matches_event(event: TimelineEvent, search: str = "", category: str = "", event_type: str = "") -> bool:
    """Prédicat sans allocation, adapté au passage ligne par ligne de Qt."""
    return matches_normalized(event, search.casefold().strip(), category, event_type)


def matches_normalized(event: TimelineEvent, needle: str, category: str = "", event_type: str = "") -> bool:
    """Variante pour les proxies Qt, lorsque la requête est déjà normalisée."""
    return (
        (not category or str((event.file_record or {}).get("category") or "") == category)
        and (not event_type or event.event_type.identifier == event_type)
        and (not needle or needle in searchable_text(event))
    )


def searchable_text(event: TimelineEvent) -> str:
    """Return the normalized text shared by Timeline search consumers."""
    record = event.file_record or {}
    values = (
        record.get("name", ""),
        event.event_type.label,
        event.source.label,
        event.metadata.get("Marque", ""),
        event.metadata.get("Modèle", ""),
        event.metadata.get("Logiciel", ""),
    )
    return " ".join(str(value) for value in values).casefold()
