"""Instrumentation légère, activée uniquement avec ``CARVEX_PERF=1``."""

from __future__ import annotations

import atexit
import ctypes
import logging
import os
import sys
import tracemalloc
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import current_thread, local
from time import perf_counter

LOGGER = logging.getLogger("carvex.performance")
ENABLED = os.environ.get("CARVEX_PERF", "").strip().casefold() in {"1", "true", "yes", "on"}
ALLOCATION_TRACKING_ENABLED = os.environ.get("CARVEX_PERF_ALLOCATIONS", "").strip().casefold() in {
    "1",
    "true",
    "yes",
    "on",
}
PERFORMANCE_LOG_FILENAME = "carvex_perf.log"
_HANDLER_KIND_ATTRIBUTE = "_carvex_performance_handler_kind"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _performance_handlers(kind: str | None = None) -> tuple[logging.Handler, ...]:
    """Retourne uniquement les handlers possédés par cette instrumentation."""
    return tuple(
        handler
        for handler in LOGGER.handlers
        if (handler_kind := getattr(handler, _HANDLER_KIND_ATTRIBUTE, None)) is not None
        and (kind is None or handler_kind == kind)
    )


def configure_performance_logging(log_path: Path | None = None) -> Path | None:
    """Configure une sortie terminal et un fichier UTF-8 idempotents en mode perf."""
    if not ENABLED:
        return None

    target_path = (log_path or Path.cwd() / PERFORMANCE_LOG_FILENAME).resolve()
    formatter = logging.Formatter(_LOG_FORMAT)
    LOGGER.setLevel(logging.INFO)

    for handler in _performance_handlers("file"):
        if Path(handler.baseFilename).resolve() == target_path:
            handler.setFormatter(formatter)
            break
        LOGGER.removeHandler(handler)
        handler.flush()
        handler.close()
    else:
        file_handler = logging.FileHandler(target_path, mode="a", encoding="utf-8")
        setattr(file_handler, _HANDLER_KIND_ATTRIBUTE, "file")
        file_handler.setFormatter(formatter)
        LOGGER.addHandler(file_handler)

    if not _performance_handlers("stream"):
        stream_handler = logging.StreamHandler()
        setattr(stream_handler, _HANDLER_KIND_ATTRIBUTE, "stream")
        stream_handler.setFormatter(formatter)
        LOGGER.addHandler(stream_handler)

    return target_path


def flush_performance_logging() -> None:
    """Force l'écriture des diagnostics déjà produits dans le fichier de session."""
    for handler in _performance_handlers():
        handler.flush()


def shutdown_performance_logging() -> None:
    """Détache proprement les handlers d'instrumentation, utile aux tests isolés."""
    for handler in _performance_handlers():
        LOGGER.removeHandler(handler)
        handler.flush()
        handler.close()


atexit.register(flush_performance_logging)

if ENABLED:
    configure_performance_logging()


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
    configure_performance_logging()
    if ALLOCATION_TRACKING_ENABLED and not tracemalloc.is_tracing():
        tracemalloc.start()


def log_memory_snapshot(label: str) -> None:
    """Journalise les compteurs mémoire disponibles sans activer tracemalloc."""
    if not ENABLED:
        return
    if tracemalloc.is_tracing():
        current, peak = tracemalloc.get_traced_memory()
        current_kib = f"{current / 1024:.1f}"
        peak_kib = f"{peak / 1024:.1f}"
    else:
        current_kib = "disabled"
        peak_kib = "disabled"
    rss = _process_rss_bytes()
    rss_kib = "unavailable" if rss is None else f"{rss / 1024:.1f}"
    LOGGER.info(
        "[Mémoire] %s tracemalloc_current_kib=%s tracemalloc_peak_kib=%s rss_kib=%s",
        label,
        current_kib,
        peak_kib,
        rss_kib,
    )


def _process_rss_bytes() -> int | None:
    """Retourne le working set lorsque la plateforme le permet sans dépendance."""
    if os.name == "nt":

        class ProcessMemoryCountersEx(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        try:
            process = ctypes.windll.kernel32.GetCurrentProcess()
            success = ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        except (AttributeError, OSError):
            return None
        return int(counters.WorkingSetSize) if success else None
    if sys.platform.startswith("linux"):
        try:
            pages = int((Path("/proc/self/statm").read_text(encoding="ascii").split())[1])
            return pages * os.sysconf("SC_PAGE_SIZE")
        except (IndexError, OSError, ValueError):
            return None
    return None


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
_operation_local = local()
_recent_operations: deque[OperationTimingEntry] = deque(maxlen=24)


@dataclass(frozen=True, slots=True)
class OperationTimingEntry:
    """Trace compacte d'une opération pouvant occuper un thread applicatif."""

    component: str
    operation: str
    thread_name: str
    thread_id: int
    depth: int
    duration_ms: float


def recent_operations() -> tuple[OperationTimingEntry, ...]:
    """Expose un historique borné uniquement pour le diagnostic opt-in."""
    return tuple(_recent_operations) if ENABLED else ()


def current_operation() -> str | None:
    """Retourne le contexte actif du thread courant, sans dépendance Qt."""
    stack = getattr(_operation_local, "stack", ())
    return " > ".join(stack) if stack else None


@contextmanager
def operation(component: str, name: str) -> Iterator[None]:
    """Mesure une opération applicative et journalise seulement les blocs significatifs."""
    if not ENABLED:
        yield
        return
    stack = getattr(_operation_local, "stack", None)
    if stack is None:
        stack = []
        _operation_local.stack = stack
    label = f"{component}.{name}"
    stack.append(label)
    started = perf_counter()
    try:
        yield
    finally:
        duration_ms = (perf_counter() - started) * 1000
        depth = len(stack) - 1
        stack.pop()
        thread = current_thread()
        entry = OperationTimingEntry(
            component=component,
            operation=name,
            thread_name=thread.name,
            thread_id=thread.ident or 0,
            depth=depth,
            duration_ms=duration_ms,
        )
        _recent_operations.append(entry)
        if duration_ms >= 100:
            threshold = (
                ">10s"
                if duration_ms >= 10_000
                else (
                    ">5s"
                    if duration_ms >= 5_000
                    else ">1s" if duration_ms >= 1_000 else ">500ms" if duration_ms >= 500 else ">100ms"
                )
            )
            LOGGER.warning(
                "[UI] BLOCK %s duration_ms=%.2f thread=%s thread_id=%d depth=%d operation=%s",
                threshold,
                duration_ms,
                entry.thread_name,
                entry.thread_id,
                entry.depth,
                label,
            )


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
    if ALLOCATION_TRACKING_ENABLED and not tracemalloc.is_tracing():
        tracemalloc.start()
    started = perf_counter()
    before = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else None
    try:
        yield
    finally:
        after, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (None, None)
        details = " ".join(f"{key}={value}" for key, value in metrics.items())
        LOGGER.info(
            "performance operation=%s duration_ms=%.2f allocated_kib=%s peak_kib=%s %s",
            operation,
            (perf_counter() - started) * 1000,
            "disabled" if before is None or after is None else f"{(after - before) / 1024:.1f}",
            "disabled" if peak is None else f"{peak / 1024:.1f}",
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
