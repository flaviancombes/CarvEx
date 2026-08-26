"""Clés de regroupement extensibles pour la vue et les futurs exports."""

from __future__ import annotations

from collections.abc import Callable

from timeline.event import TimelineEvent

GroupKey = Callable[[TimelineEvent], str]


def chronological(event: TimelineEvent) -> str:
    return event.date.isoformat()


def by_file(event: TimelineEvent) -> str:
    """Regroupe la projection UI par identifiant stable du fichier."""
    record = event.file_record or {}
    return str(record.get("file_id") or event.event_id)


def by_file_type(event: TimelineEvent) -> str:
    return str((event.file_record or {}).get("category") or "Inconnu")


def by_day(event: TimelineEvent) -> str:
    return event.date.strftime("%Y-%m-%d")


def by_month(event: TimelineEvent) -> str:
    return event.date.strftime("%Y-%m")


def by_year(event: TimelineEvent) -> str:
    return event.date.strftime("%Y")


def by_source(event: TimelineEvent) -> str:
    return event.source.label


def by_camera(event: TimelineEvent) -> str:
    return " ".join(str(event.metadata.get(key, "")) for key in ("Marque", "Modèle")).strip() or "Non renseigné"


GROUPINGS: dict[str, GroupKey] = {
    "Fichier": by_file,
    "Chronologie": chronological,
    "Type de fichier": by_file_type,
    "Jour": by_day,
    "Mois": by_month,
    "Année": by_year,
    "Source": by_source,
    "Appareil photo": by_camera,
}
