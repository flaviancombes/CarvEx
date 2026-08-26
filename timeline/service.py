"""Service de timeline partagé par le panneau existant et les vues applicatives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from metadata.manager import MetadataManager
from timeline.engine import TimelineEngine
from timeline.event import TimelineEvent
from timeline.manager import TimelineManager, build_default_manager
from timeline.repository import TimelineRepository


class TimelineService:
    def __init__(self, manager: TimelineManager) -> None:
        self.manager = manager
        self.engine = TimelineEngine(manager)
        self.repository = TimelineRepository(self.engine)

    def set_records(self, records: Sequence[Mapping[str, object]]) -> None:
        self.repository.set_records(records)

    def all_events(self) -> tuple[TimelineEvent, ...]:
        return self.repository.all_events()

    def events_for(self, file_record: Mapping[str, object]) -> tuple[TimelineEvent, ...]:
        return self.repository.events_for_file(file_record)

    def start_build(self, *, retain_events: bool = True):
        return self.repository.start_build(retain_events=retain_events)


def build_default_service(metadata_manager: MetadataManager) -> TimelineService:
    return TimelineService(build_default_manager(metadata_manager))
