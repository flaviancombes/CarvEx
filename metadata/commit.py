"""Commit séquentiel des lots, réservé au thread propriétaire du projet."""

from __future__ import annotations

from collections.abc import Callable
from threading import get_ident
from time import perf_counter

from metadata.indexing import MetadataBatchResult, MetadataIndexingService
from metadata.store import MetadataStore
from utils.performance import pipeline_stage


class MetadataCommitService:
    """Applique Store → Index → état → checkpoint depuis un seul thread."""

    def __init__(self, store: MetadataStore, indexing: MetadataIndexingService, flush: Callable[[], None]) -> None:
        self._store = store
        self._indexing = indexing
        self._flush = flush
        self._owner_thread = get_ident()
        self._checkpoint_before_pending_flush = None

    def commit(self, result: MetadataBatchResult) -> None:
        if get_ident() != self._owner_thread:
            raise RuntimeError("Seul le thread propriétaire du projet peut committer les métadonnées.")
        with pipeline_stage("Préimage Checkpoint"):
            if self._checkpoint_before_pending_flush is None:
                self._checkpoint_before_pending_flush = self._indexing.checkpoint()
        with pipeline_stage("MetadataStore.apply_batch_deferred"):
            self._store.apply_batch_deferred(result.results)
        with pipeline_stage("MetadataIndexingService.complete"):
            self._indexing.complete(result)

    def flush_pending(self, on_timing: Callable[[str, float], None] | None = None) -> None:
        """Persist committed batches at an explicit project lifecycle checkpoint."""
        if get_ident() != self._owner_thread:
            raise RuntimeError("Seul le thread propriÃ©taire du projet peut sauvegarder les mÃ©tadonnÃ©es.")
        started = perf_counter()
        try:
            checkpoint_started = perf_counter()
            with pipeline_stage("MetadataIndexingService.checkpoint"):
                checkpoint = self._indexing.checkpoint()
            if on_timing is not None:
                on_timing("Génération du Checkpoint", (perf_counter() - checkpoint_started) * 1000)
            with pipeline_stage("MetadataStore.flush_pending"):
                self._store.flush_pending(self._flush, checkpoint, on_timing=on_timing)
        except Exception:
            if self._checkpoint_before_pending_flush is not None:
                self._indexing.restore_checkpoint(self._checkpoint_before_pending_flush)
            self._checkpoint_before_pending_flush = None
            raise
        finally:
            if on_timing is not None:
                on_timing("MetadataCommitService", (perf_counter() - started) * 1000)
        self._checkpoint_before_pending_flush = None
