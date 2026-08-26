"""Modèle métier immuable d'un événement de chronologie."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from timeline.source import EventSource, EventType


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    event_type: EventType
    date: datetime
    source: EventSource
    confidence: Confidence = Confidence.HIGH
    comment: str | None = None
    is_anomaly: bool = False
    event_id: str = ""
    file_record: Mapping[str, object] | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
