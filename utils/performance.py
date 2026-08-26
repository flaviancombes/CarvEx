"""Instrumentation légère, activée uniquement avec ``CARVEX_PERF=1``."""

from __future__ import annotations

import logging
import os
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import perf_counter

LOGGER = logging.getLogger("carvex.performance")
ENABLED = os.environ.get("CARVEX_PERF", "").strip().casefold() in {"1", "true", "yes", "on"}

if ENABLED:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def format_byte_size(value: object) -> str:
    """Rend une taille en octets avec les unités IEC, sans altérer sa valeur métier."""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return "" if value is None else str(value)
    if size < 1024:
        return f"{size} o"
    units = ("KiB", "MiB", "GiB", "TiB", "PiB")
    amount = float(size)
    for unit in units:
        amount /= 1024
        if amount < 1024 or unit == units[-1]:
            precision = 2 if amount < 10 else 1
            return f"{amount:.{precision}f}".replace(".", ",") + f" {unit}"
    return f"{size} o"


def enable() -> None:
    """Active la collecte programmatique pour les tests et sessions développeur."""
    global ENABLED
    ENABLED = True
    if not tracemalloc.is_tracing():
        tracemalloc.start()


@dataclass(frozen=True, slots=True)
class IndexingTimingEntry:
    """Mesure immuable d'une phase terminale de l'indexation."""

    label: str
    started_at: datetime
    finished_at: datetime
    duration_ms: float


@dataclass(slots=True)
class IndexingCompletionReport:
    """Collecte des mesures passives entre la fin des workers et le retour Qt."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _started_at: float = field(default_factory=perf_counter, init=False)
    _last_stage_end: float = field(init=False)
    entries: list[IndexingTimingEntry] = field(default_factory=list)
    _finished: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._last_stage_end = self._started_at

    @contextmanager
    def stage(self, label: str) -> Iterator[None]:
        started = perf_counter()
        started_at = datetime.now(UTC)
        try:
            yield
        finally:
            self.record(label, started_at, (perf_counter() - started) * 1000)

    def record_elapsed(self, label: str, duration_ms: float) -> None:
        """Ajoute une mesure fournie par un sous-composant instrumenté."""
        finished_at = datetime.now(UTC)
        self.record(label, finished_at - timedelta(milliseconds=duration_ms), duration_ms, finished_at)

    def record(
        self,
        label: str,
        started_at: datetime,
        duration_ms: float,
        finished_at: datetime | None = None,
    ) -> None:
        finished_at = finished_at or datetime.now(UTC)
        self.entries.append(IndexingTimingEntry(label, started_at, finished_at, duration_ms))
        self._last_stage_end = perf_counter()

    def finish(self) -> None:
        """Journalise le bilan après le retour de la boucle d'événements Qt."""
        if self._finished:
            return
        self._finished = True
        now = perf_counter()
        self.record("Interface prête", datetime.now(UTC), (now - self._last_stage_end) * 1000)
        if not ENABLED:
            return
        for entry in self.entries:
            LOGGER.info("[Indexation] %-32s %s", entry.label, self._format_duration(entry.duration_ms))
        LOGGER.info(
            "[Indexation] Temps total post-indexation : %s",
            self._format_duration((now - self._started_at) * 1000),
        )

    @staticmethod
    def _format_duration(duration_ms: float) -> str:
        milliseconds = max(0, round(duration_ms))
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1_000)
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


@dataclass(slots=True)
class _PipelineProfileStat:
    calls: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    def add(self, duration_ms: float) -> None:
        self.calls += 1
        self.total_ms += duration_ms
        self.max_ms = max(self.max_ms, duration_ms)


@dataclass(slots=True)
class PipelineProfile:
    """Profil hiérarchique opt-in d'une séquence métier terminale."""

    label: str
    _started_at: float = field(default_factory=perf_counter, init=False)
    _stats: dict[tuple[str, ...], _PipelineProfileStat] = field(default_factory=dict, init=False)
    _stack: list[str] = field(default_factory=list, init=False)
    _finished: bool = field(default=False, init=False)

    @contextmanager
    def stage(self, label: str) -> Iterator[None]:
        self._stack.append(label)
        started = perf_counter()
        try:
            yield
        finally:
            duration_ms = (perf_counter() - started) * 1000
            path = tuple(self._stack)
            self._stats.setdefault(path, _PipelineProfileStat()).add(duration_ms)
            self._stack.pop()

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        total_ms = (perf_counter() - self._started_at) * 1000
        if not ENABLED:
            return
        LOGGER.info("[Profil] %s : %s", self.label, self._format_duration(total_ms))
        for path in sorted(self._stats):
            stat = self._stats[path]
            if stat.total_ms < 50 and stat.max_ms < 50:
                continue
            indent = "  " * (len(path) - 1)
            percent = 0.0 if total_ms <= 0 else stat.total_ms / total_ms * 100
            LOGGER.info(
                "[Profil] %s%s — appels: %d, moyenne: %.2f ms, max: %.2f ms, total: %s (%.1f%%)",
                indent,
                path[-1],
                stat.calls,
                stat.total_ms / stat.calls,
                stat.max_ms,
                self._format_duration(stat.total_ms),
                percent,
            )

    @staticmethod
    def _format_duration(duration_ms: float) -> str:
        milliseconds = max(0, round(duration_ms))
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1_000)
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


_active_pipeline_profile: PipelineProfile | None = None


def start_pipeline_profile(label: str = "Pipeline final") -> None:
    """Démarre une mesure métier uniquement lorsque l'instrumentation est active."""
    global _active_pipeline_profile
    if ENABLED and _active_pipeline_profile is None:
        _active_pipeline_profile = PipelineProfile(label)


@contextmanager
def pipeline_stage(label: str) -> Iterator[None]:
    """Mesure un nœud du profil actif, sans coût hors mode instrumentation."""
    profile = _active_pipeline_profile
    if profile is None:
        yield
        return
    with profile.stage(label):
        yield


def finish_pipeline_profile() -> None:
    """Journalise puis libère la séquence métier active."""
    global _active_pipeline_profile
    if _active_pipeline_profile is not None:
        _active_pipeline_profile.finish()
        _active_pipeline_profile = None


@contextmanager
def measure(operation: str, **metrics: object) -> Iterator[None]:
    """Journalise une durée et l'allocation Python approximative, si activé."""
    if not ENABLED:
        yield
        return
    if not tracemalloc.is_tracing():
        tracemalloc.start()
    started = perf_counter()
    before, _ = tracemalloc.get_traced_memory()
    try:
        yield
    finally:
        after, peak = tracemalloc.get_traced_memory()
        details = " ".join(f"{key}={value}" for key, value in metrics.items())
        LOGGER.info(
            "performance operation=%s duration_ms=%.2f allocated_kib=%.1f peak_kib=%.1f %s",
            operation,
            (perf_counter() - started) * 1000,
            (after - before) / 1024,
            peak / 1024,
            details,
        )


def log_cache_sizes(metadata_manager=None, timeline_service=None) -> None:
    """Expose les tailles de caches connus sans dépendance métier inverse."""
    if not ENABLED:
        return
    metadata_size = len(getattr(getattr(metadata_manager, "_cache", None), "_entries", {}))
    timeline_size = len(getattr(getattr(getattr(timeline_service, "manager", None), "_cache", None), "_entries", {}))
    repository_events = getattr(getattr(timeline_service, "repository", None), "_events", None)
    LOGGER.info(
        "performance caches metadata_entries=%d timeline_file_entries=%d timeline_events=%d",
        metadata_size,
        timeline_size,
        len(repository_events) if repository_events is not None else 0,
    )
