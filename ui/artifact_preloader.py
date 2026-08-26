"""Préchargement asynchrone des artefacts pour les filtres de fichiers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from analysis.artifact_classifier import ArtifactClassifier
from core.file_identity import require_file_id
from metadata.manager import MetadataManager


class _PreloadSignals(QObject):
    batch_ready = Signal(int, object)
    completed = Signal(int)


class _ArtifactPreloadTask(QRunnable):
    def __init__(
        self,
        records: Sequence[Mapping[str, Any]],
        metadata_manager: MetadataManager,
        classifier: ArtifactClassifier,
        cancelled: Event,
        generation: int,
        signals: _PreloadSignals,
        batch_size: int,
    ) -> None:
        super().__init__()
        self._records = records
        self._metadata_manager = metadata_manager
        self._classifier = classifier
        self._cancelled = cancelled
        self._generation = generation
        self._signals = signals
        self._batch_size = batch_size

    def run(self) -> None:
        processed = 0
        updated_file_ids: list[str] = []
        for record in self._records:
            if self._cancelled.is_set():
                return
            if not _is_image(record):
                continue
            if self._classifier.cached_for(record) is None:
                metadata = self._metadata_manager.cached_or_stored(record)
                if metadata is None:
                    continue
                self._classifier.classify(record, metadata)
                updated_file_ids.append(require_file_id(record))
            processed += 1
            if processed % self._batch_size == 0:
                if updated_file_ids:
                    self._signals.batch_ready.emit(self._generation, tuple(updated_file_ids))
                    updated_file_ids.clear()
        if not self._cancelled.is_set():
            if updated_file_ids:
                self._signals.batch_ready.emit(self._generation, tuple(updated_file_ids))
            self._signals.completed.emit(self._generation)


class ArtifactPreloader(QObject):
    """Orchestre un calcul différé hors UI et notifie uniquement les lots prêts."""

    cache_updated = Signal(object)
    completed = Signal()

    def __init__(
        self,
        metadata_manager: MetadataManager,
        classifier: ArtifactClassifier,
        parent=None,
        thread_pool: QThreadPool | None = None,
        batch_size: int = 32,
    ) -> None:
        super().__init__(parent)
        if batch_size <= 0:
            raise ValueError("La taille de lot des artefacts doit être positive.")
        self._metadata_manager = metadata_manager
        self._classifier = classifier
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._batch_size = batch_size
        self._generation = 0
        self._cancelled: Event | None = None
        self._signals = _PreloadSignals()
        self._signals.batch_ready.connect(self._on_batch_ready)
        self._signals.completed.connect(self._on_completed)

    def preload(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Démarre un unique calcul asynchrone pour le corpus courant."""
        self.cancel()
        if not records:
            return
        self._generation += 1
        cancelled = Event()
        self._cancelled = cancelled
        task = _ArtifactPreloadTask(
            records,
            self._metadata_manager,
            self._classifier,
            cancelled,
            self._generation,
            self._signals,
            self._batch_size,
        )
        self._thread_pool.start(task)

    def cancel(self) -> None:
        if self._cancelled is not None:
            self._cancelled.set()
        self._generation += 1
        self._cancelled = None

    def clear_cache(self) -> None:
        """Forget cached artifacts from the project that is being detached."""
        self.cancel()
        self._classifier.clear()

    def _on_batch_ready(self, generation: int, file_ids: tuple[str, ...]) -> None:
        if generation == self._generation:
            self.cache_updated.emit(file_ids)

    def _on_completed(self, generation: int) -> None:
        if generation == self._generation:
            self._cancelled = None
            self.completed.emit()


def _is_image(record: Mapping[str, Any]) -> bool:
    return record.get("category") == "Images" or str(record.get("mime") or "").lower().startswith("image/")
