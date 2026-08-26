"""Infrastructure pure d'orchestration de l'indexation de métadonnées."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Event, Lock
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

from metadata.base import MetadataResult

if TYPE_CHECKING:
    from metadata.manager import MetadataManager


LOGGER = logging.getLogger(__name__)


class MetadataIndexingState(StrEnum):
    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MetadataIndexingEntry:
    """État persistable et horodaté d'un fichier dans l'indexation."""

    file_id: str
    state: MetadataIndexingState
    changed_at: datetime

    def __post_init__(self) -> None:
        if not self.file_id:
            raise ValueError("Un file_id est obligatoire.")
        if not isinstance(self.state, MetadataIndexingState):
            raise ValueError("L'état d'indexation est invalide.")
        if self.changed_at.tzinfo is None or self.changed_at.utcoffset() is None:
            raise ValueError("La date d'état doit contenir un fuseau horaire.")


@dataclass(frozen=True, slots=True)
class MetadataIndexingCheckpoint:
    """Format officiel, versionné et immuable de l'état d'indexation."""

    CURRENT_SCHEMA_VERSION: ClassVar[int] = 1

    schema_version: int
    index_version: int
    last_checkpoint_sequence: int
    total_count: int
    indexed_count: int
    failed_count: int
    entries: Mapping[str, MetadataIndexingEntry]

    def __post_init__(self) -> None:
        if self.schema_version != self.CURRENT_SCHEMA_VERSION:
            raise ValueError(f"Version de checkpoint incompatible : {self.schema_version}")
        if self.index_version < 1 or self.last_checkpoint_sequence < -1:
            raise ValueError("Les versions et séquences de checkpoint sont invalides.")
        if min(self.total_count, self.indexed_count, self.failed_count) < 0:
            raise ValueError("Les compteurs de checkpoint doivent être positifs.")
        normalized = dict(self.entries)
        if self.total_count != len(normalized):
            raise ValueError("Le total du checkpoint doit correspondre aux entrées.")
        if any(not isinstance(entry, MetadataIndexingEntry) for entry in normalized.values()):
            raise ValueError("Les entrées du checkpoint sont invalides.")
        if any(file_id != entry.file_id for file_id, entry in normalized.items()):
            raise ValueError("La clé d'une entrée doit correspondre à son file_id.")
        if self.indexed_count != sum(entry.state is MetadataIndexingState.INDEXED for entry in normalized.values()):
            raise ValueError("Le compteur indexed est incohérent.")
        if self.failed_count != sum(entry.state is MetadataIndexingState.FAILED for entry in normalized.values()):
            raise ValueError("Le compteur failed est incohérent.")
        object.__setattr__(self, "entries", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class MetadataBatch:
    sequence: int
    file_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.sequence < 0 or not self.file_ids or len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError("Un lot doit avoir une séquence positive et des file_id uniques.")


@dataclass(frozen=True, slots=True)
class MetadataBatchResult:
    batch: MetadataBatch
    results: tuple[tuple[str, MetadataResult], ...]
    failed_ids: tuple[str, ...] = ()
    deferred_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        result_ids = tuple(file_id for file_id, _result in self.results)
        covered = set(result_ids) | set(self.failed_ids) | set(self.deferred_ids)
        if covered != set(self.batch.file_ids):
            raise ValueError("Le résultat doit couvrir exactement les fichiers du lot.")
        if len(covered) != len(result_ids) + len(self.failed_ids) + len(self.deferred_ids):
            raise ValueError("Un fichier ne peut appartenir qu'à un seul résultat de lot.")


@dataclass(frozen=True, slots=True)
class MetadataProgress:
    total: int
    indexed: int
    indexing: int
    failed: int
    elapsed_seconds: float = 0.0
    current_file_id: str | None = None
    current_category: str | None = None

    @property
    def remaining(self) -> int:
        return self.total - self.indexed - self.indexing - self.failed

    @property
    def percentage(self) -> float:
        return 0.0 if not self.total else (self.indexed + self.failed) * 100 / self.total

    @property
    def items_per_second(self) -> float:
        completed = self.indexed + self.failed
        return 0.0 if not self.elapsed_seconds else completed / self.elapsed_seconds

    @property
    def estimated_remaining_seconds(self) -> float | None:
        speed = self.items_per_second
        return None if speed <= 0 else self.remaining / speed


class MetadataIndexingService:
    """Orchestre des lots immuables sans extraction, écriture ni dépendance Qt."""

    def __init__(self, file_ids: tuple[str, ...] = ()) -> None:
        if len(set(file_ids)) != len(file_ids):
            raise ValueError("Les file_id doivent être uniques.")
        self._states = {file_id: MetadataIndexingState.NOT_INDEXED for file_id in file_ids}
        now = datetime.now(UTC)
        self._changed_at = {file_id: now for file_id in file_ids}
        self._queue: deque[MetadataBatch] = deque()
        self._completed: deque[MetadataBatchResult] = deque()
        self._next_sequence = 0
        self._completed_lock = Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._futures: dict[Future[MetadataBatchResult], MetadataBatch] = {}
        self._cancelled = Event()
        self._records: Iterable[Mapping[str, object]] | None = None
        self._metadata_manager: MetadataManager | None = None
        self._batch_size = 64
        self._max_workers = 1
        self._started_at: float | None = None
        self._current_file_id: str | None = None
        self._current_category: str | None = None
        self._indexed_count = 0
        self._indexing_count = 0
        self._failed_count = 0

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: MetadataIndexingCheckpoint | None,
        known_file_ids: tuple[str, ...] = (),
    ) -> MetadataIndexingService:
        """Hydrate passivement le service sans planifier ni modifier le projet."""
        if checkpoint is None:
            return cls(known_file_ids)
        service = cls(tuple(checkpoint.entries))
        service._states = {file_id: entry.state for file_id, entry in checkpoint.entries.items()}
        service._changed_at = {file_id: entry.changed_at for file_id, entry in checkpoint.entries.items()}
        service._next_sequence = checkpoint.last_checkpoint_sequence + 1
        service._indexed_count = checkpoint.indexed_count
        service._failed_count = checkpoint.failed_count
        service._indexing_count = sum(
            entry.state is MetadataIndexingState.INDEXING for entry in checkpoint.entries.values()
        )
        return service

    def state_for(self, file_id: str) -> MetadataIndexingState:
        return self._states[file_id]

    def changed_at_for(self, file_id: str) -> datetime:
        return self._changed_at[file_id]

    @property
    def progress(self) -> MetadataProgress:
        elapsed = 0.0 if self._started_at is None else max(0.0, time.monotonic() - self._started_at)
        return MetadataProgress(
            len(self._states),
            self._indexed_count,
            self._indexing_count,
            self._failed_count,
            elapsed,
            self._current_file_id,
            self._current_category,
        )

    @property
    def is_running(self) -> bool:
        return bool(self._executor is not None and (self._futures or self._records is not None))

    @property
    def has_completed(self) -> bool:
        with self._completed_lock:
            return bool(self._completed)

    def start(
        self,
        records: Sequence[Mapping[str, object]],
        manager: MetadataManager,
        *,
        batch_size: int = 64,
        max_workers: int = 1,
    ) -> None:
        """Planifie les fichiers non indexés sans toucher au stockage du projet."""
        if self.is_running:
            raise RuntimeError("Une indexation de métadonnées est déjà en cours.")
        if batch_size < 1 or max_workers < 1:
            raise ValueError("La taille de lot et le nombre de workers doivent être positifs.")
        self._register_records(records)
        self.normalize_interrupted_states()
        self._records = iter(records)
        self._metadata_manager = manager
        self._batch_size = batch_size
        self._max_workers = max_workers
        self._cancelled.clear()
        self._started_at = time.monotonic()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="metadata-index")
        self.schedule_workers()

    def schedule_workers(self) -> None:
        """Remplit les emplacements workers disponibles avec des lots FIFO bornés."""
        if self._executor is None or self._records is None or self._cancelled.is_set():
            self._shutdown_if_idle()
            return
        while len(self._futures) < self._max_workers:
            batch_records = self._next_batch_records()
            if not batch_records:
                self._records = None
                break
            batch = self.enqueue(tuple(batch_records))
            worker = MetadataExtractionWorker(
                self._metadata_manager,
                self,
                batch,
                batch_records,
                self._cancelled,
            )
            future = self._executor.submit(worker.run)
            self._futures[future] = batch
        self._shutdown_if_idle()

    def collect_completed(self) -> tuple[MetadataBatchResult, ...]:
        """Retourne les lots terminés dans leur ordre FIFO de production."""
        with self._completed_lock:
            completed = tuple(self._completed)
            self._completed.clear()
        for future in tuple(self._futures):
            if future.done():
                batch = self._futures.pop(future)
                try:
                    future.result()
                except Exception:
                    LOGGER.exception("Échec inattendu du worker de métadonnées pour le lot %s", batch.sequence)
                    completed = (*completed, MetadataBatchResult(batch, (), batch.file_ids))
        self._shutdown_if_idle()
        return completed

    def cancel(self) -> None:
        """Interdit tout nouveau lot et demande l'arrêt coopératif des workers."""
        self._cancelled.set()
        self._records = None

    def shutdown(self) -> None:
        """Attend les workers ; les résultats produits restent disponibles au commit."""
        self.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
        self._futures.clear()

    def enqueue(self, file_ids: tuple[str, ...]) -> MetadataBatch:
        if (
            not file_ids
            or len(set(file_ids)) != len(file_ids)
            or any(self._states[item] is not MetadataIndexingState.NOT_INDEXED for item in file_ids)
        ):
            raise ValueError("Seuls des fichiers NOT_INDEXED uniques peuvent être planifiés.")
        batch = MetadataBatch(self._next_sequence, file_ids)
        self._next_sequence += 1
        self._queue.append(batch)
        for file_id in file_ids:
            self._set_state(file_id, MetadataIndexingState.INDEXING)
            self._changed_at[file_id] = datetime.now(UTC)
        return batch

    def dequeue(self) -> MetadataBatch | None:
        return self._queue.popleft() if self._queue else None

    def submit(self, result: MetadataBatchResult) -> None:
        """Réceptionne un résultat produit par un worker, sans écriture métier."""
        with self._completed_lock:
            self._completed.append(result)

    def dequeue_completed(self) -> MetadataBatchResult | None:
        with self._completed_lock:
            return self._completed.popleft() if self._completed else None

    def complete(self, result: MetadataBatchResult) -> None:
        for file_id, _metadata in result.results:
            self._set_state(file_id, MetadataIndexingState.INDEXED)
            self._changed_at[file_id] = datetime.now(UTC)
        for file_id in result.failed_ids:
            self._set_state(file_id, MetadataIndexingState.FAILED)
            self._changed_at[file_id] = datetime.now(UTC)
        for file_id in result.deferred_ids:
            self._set_state(file_id, MetadataIndexingState.NOT_INDEXED)
            self._changed_at[file_id] = datetime.now(UTC)

    def checkpoint_after(self, result: MetadataBatchResult, index_version: int = 1) -> MetadataIndexingCheckpoint:
        """Construit l'état cible d'un lot sans modifier l'état courant."""
        states = dict(self._states)
        changed_at = dict(self._changed_at)
        now = datetime.now(UTC)
        for file_id, _metadata in result.results:
            states[file_id] = MetadataIndexingState.INDEXED
            changed_at[file_id] = now
        for file_id in result.failed_ids:
            states[file_id] = MetadataIndexingState.FAILED
            changed_at[file_id] = now
        for file_id in result.deferred_ids:
            states[file_id] = MetadataIndexingState.NOT_INDEXED
            changed_at[file_id] = now
        return self._checkpoint_from_state(states, changed_at, index_version)

    def checkpoint(self, index_version: int = 1) -> MetadataIndexingCheckpoint:
        """Return the current in-memory checkpoint without mutating scheduling state."""
        return self._checkpoint_from_state(self._states, self._changed_at, index_version)

    def restore_checkpoint(self, checkpoint: MetadataIndexingCheckpoint) -> None:
        """Remplace l'état mémoire après le succès d'un commit atomique."""
        self._states = {file_id: entry.state for file_id, entry in checkpoint.entries.items()}
        self._changed_at = {file_id: entry.changed_at for file_id, entry in checkpoint.entries.items()}
        self._next_sequence = checkpoint.last_checkpoint_sequence + 1
        self._indexed_count = checkpoint.indexed_count
        self._failed_count = checkpoint.failed_count
        self._indexing_count = sum(
            entry.state is MetadataIndexingState.INDEXING for entry in checkpoint.entries.values()
        )

    def _register_records(self, records: Iterable[Mapping[str, object]]) -> None:
        now = datetime.now(UTC)
        for record in records:
            file_id = self._file_id_for(record)
            if file_id not in self._states:
                self._states[file_id] = MetadataIndexingState.NOT_INDEXED
                self._changed_at[file_id] = now

    def normalize_interrupted_states(self) -> None:
        """Reclasse passivement les lots interrompus en attente de reprise."""
        now = datetime.now(UTC)
        for file_id, state in tuple(self._states.items()):
            if state is MetadataIndexingState.INDEXING:
                self._set_state(file_id, MetadataIndexingState.NOT_INDEXED)
                self._changed_at[file_id] = now

    def _set_state(self, file_id: str, state: MetadataIndexingState) -> None:
        previous = self._states[file_id]
        if previous is state:
            return
        if previous is MetadataIndexingState.INDEXED:
            self._indexed_count -= 1
        elif previous is MetadataIndexingState.INDEXING:
            self._indexing_count -= 1
        elif previous is MetadataIndexingState.FAILED:
            self._failed_count -= 1
        if state is MetadataIndexingState.INDEXED:
            self._indexed_count += 1
        elif state is MetadataIndexingState.INDEXING:
            self._indexing_count += 1
        elif state is MetadataIndexingState.FAILED:
            self._failed_count += 1
        self._states[file_id] = state

    def _next_batch_records(self) -> dict[str, Mapping[str, object]]:
        if self._records is None:
            return {}
        batch_records: dict[str, Mapping[str, object]] = {}
        while len(batch_records) < self._batch_size:
            try:
                record = next(self._records)
            except StopIteration:
                break
            file_id = self._file_id_for(record)
            if self._states[file_id] is not MetadataIndexingState.NOT_INDEXED:
                continue
            batch_records[file_id] = record
            self._current_file_id = file_id
            category = record.get("category")
            self._current_category = None if category is None else str(category)
        return batch_records

    def _shutdown_if_idle(self) -> None:
        if self._records is None and not self._futures and self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._executor = None

    @staticmethod
    def _file_id_for(record: Mapping[str, object]) -> str:
        value = record.get("file_id")
        if not isinstance(value, str) or not value:
            raise ValueError("Chaque fichier à indexer doit posséder un file_id.")
        return value

    def persistence_snapshot(self, index_version: int = 1) -> dict[str, object]:
        checkpoint = self._checkpoint_from_state(self._states, self._changed_at, index_version)
        return {
            "schema_version": checkpoint.schema_version,
            "index_version": checkpoint.index_version,
            "last_checkpoint": checkpoint.last_checkpoint_sequence,
            "total": checkpoint.total_count,
            "indexed": checkpoint.indexed_count,
            "failed": checkpoint.failed_count,
            "states": {
                file_id: {"state": state.value, "changed_at": self._changed_at[file_id].isoformat()}
                for file_id, state in self._states.items()
            },
        }

    def _checkpoint_from_state(
        self,
        states: Mapping[str, MetadataIndexingState],
        changed_at: Mapping[str, datetime],
        index_version: int,
    ) -> MetadataIndexingCheckpoint:
        entries = {
            file_id: MetadataIndexingEntry(file_id, state, changed_at[file_id]) for file_id, state in states.items()
        }
        return MetadataIndexingCheckpoint(
            MetadataIndexingCheckpoint.CURRENT_SCHEMA_VERSION,
            index_version,
            self._next_sequence - 1,
            len(entries),
            sum(entry.state is MetadataIndexingState.INDEXED for entry in entries.values()),
            sum(entry.state is MetadataIndexingState.FAILED for entry in entries.values()),
            entries,
        )


class MetadataExtractionWorker:
    """Producteur sans état de projet : extrait et soumet un lot immuable."""

    def __init__(
        self,
        manager: MetadataManager,
        service: MetadataIndexingService,
        batch: MetadataBatch,
        records_by_id: Mapping[str, Mapping[str, object]],
        cancelled: Event | None = None,
    ) -> None:
        self._manager = manager
        self._service = service
        self._batch = batch
        self._records = records_by_id
        self._cancelled = cancelled or Event()

    def run(self) -> MetadataBatchResult:
        results: list[tuple[str, MetadataResult]] = []
        failed: list[str] = []
        for file_id in self._batch.file_ids:
            if self._cancelled.is_set():
                deferred = tuple(item for item in self._batch.file_ids if item not in {key for key, _ in results})
                break
            record = self._records.get(file_id)
            if record is None:
                failed.append(file_id)
                continue
            try:
                results.append((file_id, self._manager.extract_transient(record)))
            except Exception:
                LOGGER.exception("Échec de l'extraction de métadonnées pour %s", file_id)
                failed.append(file_id)
        else:
            deferred = ()
        result = MetadataBatchResult(self._batch, tuple(results), tuple(failed), deferred)
        self._service.submit(result)
        return result
