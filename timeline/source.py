"""Vocabulaire extensible des types et origines d'événements."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EventSource:
    identifier: str
    label: str


@dataclass(frozen=True, slots=True)
class EventType:
    identifier: str
    label: str
    icon: str


EXIF = EventSource("exif", "Métadonnées EXIF")
FILESYSTEM = EventSource("filesystem", "Système de fichiers")

EXIF_CAPTURED = EventType("exif.captured", "Prise de vue", "📷")
EXIF_DIGITIZED = EventType("exif.digitized", "Numérisation", "🖼")
EXIF_MODIFIED = EventType("exif.modified", "Modification EXIF", "🖼")
FILE_CREATED = EventType("filesystem.created", "Création du fichier", "💾")
FILE_MODIFIED = EventType("filesystem.modified", "Modification du fichier", "💾")
FILE_ACCESSED = EventType("filesystem.accessed", "Dernier accès", "💾")
