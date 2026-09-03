"""Shared, lazy Timeline event repository."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from threading import Event
from time import perf_counter

from timeline.engine import TimelineEngine
from timeline.event import TimelineEvent
from utils.performance import measure


class TimelineRepository:
    """Keeps report records by reference and only retains a global tuple on demand."""

    def __init__(self, engine: TimelineEngine) -> None:
        self._engine = engine
        self._records: Sequence[Mapping[str, object]] = ()
        self._events: tuple[TimelineEvent, ...] | None = None

    def set_records(self, records: Sequence[Mapping[str, object]]) -> None:
        """Attach report records without copying them and release the previous event cache."""
        self._records = records
        self._events = None
        self._engine.clear_cache()

    @property
    def record_count(self) -> int:
        """Nombre de preuves source, disponible sans matérialiser d'événement."""
        return len(self._records)

    def all_events(self) -> tuple[TimelineEvent, ...]:
        """Materialize the legacy global index only for consumers explicitly requesting it."""
        if self._events is None:
            self._events = tuple(event for record in self._records for event in self._engine.events_for(record))
        return self._events

    def start_build(self, *, retain_events: bool = True) -> TimelineBuildSession:
        """Create a cancellable event stream without blocking the caller thread."""
        if self._events is not None:
            return TimelineBuildSession(
                iter(()),
                self,
                retain_events=retain_events,
                complete=True,
                ready_events=self._events,
            )
        return TimelineBuildSession(iter(self._records), self, retain_events=retain_events)

    def events_for_file(self, file_record: Mapping[str, object]) -> tuple[TimelineEvent, ...]:
        return self._engine.events_for(file_record)


@dataclass(slots=True)
class TimelineBuildSession:
    """Build Timeline events in bounded batches; retaining a global index is optional."""

    records: Iterator[Mapping[str, object]]
    repository: TimelineRepository
    retain_events: bool = True
    complete: bool = False
    ready_events: tuple[TimelineEvent, ...] = ()
    _events: list[TimelineEvent] | None = field(default=None, init=False)
    _cancelled: Event = field(default_factory=Event, init=False)
    processed_records: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.retain_events:
            self._events = []

    def cancel(self) -> None:
        self._cancelled.set()

    def next_batch(
        self,
        record_count: int,
        *,
        time_budget_ms: float | None = None,
    ) -> tuple[tuple[TimelineEvent, ...], bool]:
        """Build at most ``record_count`` records within an optional time budget."""
        if self.complete:
            if not self.ready_events:
                return (), True
            ready, self.ready_events = self.ready_events[:record_count], self.ready_events[record_count:]
            return ready, not self.ready_events
        batch: list[TimelineEvent] = []
        deadline = perf_counter() + time_budget_ms / 1_000 if time_budget_ms is not None else None
        with measure("timeline.build_batch", records=record_count):
            try:
                for _index in range(record_count):
                    if self._cancelled.is_set():
                        self.complete = True
                        break
                    record = next(self.records)
                    self.processed_records += 1
                    new_events = self.repository._engine.events_for(record)
                    if self._events is not None:
                        self._events.extend(new_events)
                    batch.extend(new_events)
                    if deadline is not None and perf_counter() >= deadline:
                        break
            except StopIteration:
                self.complete = True
                if self._events is not None:
                    self.repository._events = tuple(self._events)
        return tuple(batch), self.complete
