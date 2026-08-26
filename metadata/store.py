"""Store projet officiel des métadonnées, indépendant du cache mémoire."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from time import perf_counter

from metadata.base import MetadataResult
from metadata.index import MetadataIndex
from metadata.indexing import MetadataIndexingCheckpoint, MetadataIndexingEntry, MetadataIndexingState
from project.stores import ProjectStore
from utils.performance import pipeline_stage


class MetadataStore:
    VERSION = 2
    FIELDS_KEY = "fields"
    INDEX_KEY = "index"
    CHECKPOINT_KEY = "indexing_checkpoint"
    VERSION_KEY = "version"

    def __init__(self, fields_store: ProjectStore, index_store: ProjectStore) -> None:
        self._fields_store = fields_store
        self._index_store = index_store
        self._index = MetadataIndex(index_store.get(self.INDEX_KEY, {}))
        self._upgrade_legacy_index_if_needed()
        self._checkpoint = self._load_checkpoint()
        self._pending_preimage: dict[str, object] | None = None
        if index_store.get(self.VERSION_KEY) != self.VERSION:
            index_store.set(self.VERSION_KEY, self.VERSION)

    def get(self, file_id: str) -> MetadataResult | None:
        fields = self._fields_store.get(file_id)
        return MetadataResult(fields=tuple(fields)) if fields is not None else None

    def set(self, file_id: str, result: MetadataResult) -> None:
        previous = self.get(file_id)
        self._fields_store.set(file_id, result.fields)
        self._index.replace(file_id, previous.fields if previous is not None else (), result.fields)
        self._index_store.set(self.INDEX_KEY, self._index.snapshot())

    def apply_batch(self, entries: tuple[tuple[str, MetadataResult], ...]) -> None:
        """Écrit un lot et restaure les valeurs mémoire si une écriture échoue."""
        previous = {file_id: self._fields_store.get(file_id) for file_id, _result in entries}
        previous_index = self._index_store.get(self.INDEX_KEY, {})
        try:
            for file_id, result in entries:
                self.set(file_id, result)
        except Exception:
            for file_id, fields in previous.items():
                if fields is None:
                    self._fields_store.delete(file_id)
                else:
                    self._fields_store.set(file_id, fields)
            self._index = MetadataIndex(previous_index)
            self._index_store.set(self.INDEX_KEY, previous_index)
            raise

    def apply_batch_with_checkpoint(
        self,
        entries: tuple[tuple[str, MetadataResult], ...],
        checkpoint: MetadataIndexingCheckpoint,
    ) -> None:
        """Applique Store, Index et checkpoint, ou restaure leur préimage exacte."""
        self._apply_batch_with_checkpoint(entries, checkpoint)

    def apply_batch_deferred(self, entries: tuple[tuple[str, MetadataResult], ...]) -> None:
        """Apply a batch in memory without rebuilding the full index snapshot.

        The metadata indexer commits small batches from the Qt owner thread.
        Serialisation is deferred to the project checkpoint; mutating the
        already materialised index remains proportional to the batch.
        """
        with pipeline_stage("MetadataStore.transaction_preimage"):
            preimage = self._transaction_preimage(entries)
        applied: list[str] = []
        try:
            for file_id, result in entries:
                existed, previous = preimage["fields"][file_id]
                self._fields_store.set(file_id, result.fields)
                with pipeline_stage("MetadataIndex.replace"):
                    self._index.replace(file_id, tuple(previous or ()) if existed else (), result.fields)
                applied.append(file_id)
        except Exception:
            self._restore_deferred_preimage(preimage, applied)
            raise
        self._capture_deferred_preimage(preimage)

    def apply_batch_with_checkpoint_and_flush(
        self,
        entries: tuple[tuple[str, MetadataResult], ...],
        checkpoint: MetadataIndexingCheckpoint,
        flush: Callable[[], None],
    ) -> None:
        """Inclut le flush du projet dans la même transaction mémoire."""
        self._apply_batch_with_checkpoint(entries, checkpoint, flush)

    def _apply_batch_with_checkpoint(
        self,
        entries: tuple[tuple[str, MetadataResult], ...],
        checkpoint: MetadataIndexingCheckpoint,
        flush: Callable[[], None] | None = None,
    ) -> None:
        if not isinstance(checkpoint, MetadataIndexingCheckpoint):
            raise TypeError("A MetadataIndexingCheckpoint is required.")
        preimage = self._transaction_preimage(entries)
        self._capture_pending_preimage(entries)
        updated_index = MetadataIndex(self._index.snapshot())
        try:
            for file_id, result in entries:
                previous = self._fields_store.get(file_id, ())
                self._fields_store.set(file_id, result.fields)
                updated_index.replace(file_id, tuple(previous or ()), result.fields)
            self._index_store.set(self.INDEX_KEY, updated_index.snapshot())
            self._index_store.set(self.CHECKPOINT_KEY, checkpoint)
            if flush is not None:
                flush()
        except Exception:
            self._restore_transaction_preimage(preimage)
            raise
        self._index = updated_index
        self._checkpoint = checkpoint

    def flush_pending(
        self,
        flush: Callable[[], None],
        checkpoint: MetadataIndexingCheckpoint | None = None,
        *,
        on_timing: Callable[[str, float], None] | None = None,
    ) -> None:
        """Flush all deferred batches, or restore their exact shared preimage."""
        checkpoint = checkpoint or self._checkpoint
        if checkpoint is None:
            self._flush_project(flush, on_timing)
            return
        if self._pending_preimage is None:
            self._persist_index_and_checkpoint(checkpoint, on_timing)
            self._checkpoint = checkpoint
            self._flush_project(flush, on_timing)
            return
        try:
            self._persist_index_and_checkpoint(checkpoint, on_timing)
            self._checkpoint = checkpoint
            self._flush_project(flush, on_timing)
        except Exception:
            self._restore_deferred_preimage(self._pending_preimage)
            self._pending_preimage = None
            raise
        self._pending_preimage = None

    def _persist_index_and_checkpoint(
        self,
        checkpoint: MetadataIndexingCheckpoint,
        on_timing: Callable[[str, float], None] | None,
    ) -> None:
        index_started = perf_counter()
        with pipeline_stage("MetadataIndex.snapshot"):
            snapshot = self._index.snapshot()
        self._index_store.set(self.INDEX_KEY, snapshot)
        if on_timing is not None:
            on_timing("MetadataIndex", (perf_counter() - index_started) * 1000)
        checkpoint_started = perf_counter()
        self._index_store.set(self.CHECKPOINT_KEY, checkpoint)
        if on_timing is not None:
            on_timing("MetadataStore / Checkpoint", (perf_counter() - checkpoint_started) * 1000)

    @staticmethod
    def _flush_project(flush: Callable[[], None], on_timing: Callable[[str, float], None] | None) -> None:
        flush_started = perf_counter()
        try:
            with pipeline_stage("ProjectRepository.flush"):
                flush()
        finally:
            if on_timing is not None:
                on_timing("ProjectRepository.flush / sauvegarde .carvex", (perf_counter() - flush_started) * 1000)

    def materialize_checkpoint(self, checkpoint: MetadataIndexingCheckpoint) -> None:
        """Expose the current coherent in-memory metadata state to a project save."""
        self._index_store.set(self.INDEX_KEY, self._index.snapshot())
        self._index_store.set(self.CHECKPOINT_KEY, checkpoint)
        self._checkpoint = checkpoint

    def contains(self, file_id: str) -> bool:
        return self._fields_store.get(file_id) is not None

    def known_file_ids(self) -> tuple[str, ...]:
        """Retourne les fichiers déjà connus du store sans extraction ni écriture."""
        return tuple(self._fields_store.keys())

    def load_checkpoint(self) -> MetadataIndexingCheckpoint | None:
        """Return the typed checkpoint without creating one for a legacy project."""
        return self._checkpoint

    def save_checkpoint(self, checkpoint: MetadataIndexingCheckpoint) -> None:
        """Persist the official metadata indexing checkpoint format."""
        if not isinstance(checkpoint, MetadataIndexingCheckpoint):
            raise TypeError("A MetadataIndexingCheckpoint is required.")
        self._index_store.set(self.CHECKPOINT_KEY, checkpoint)
        self._checkpoint = checkpoint

    @property
    def checkpoint(self) -> MetadataIndexingCheckpoint | None:
        """Expose the current checkpoint without bypassing the store."""
        return self._checkpoint

    def load_indexing_state(self) -> dict[str, object]:
        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            return {}
        return {
            "schema_version": checkpoint.schema_version,
            "index_version": checkpoint.index_version,
            "last_checkpoint": checkpoint.last_checkpoint_sequence,
            "total": checkpoint.total_count,
            "indexed": checkpoint.indexed_count,
            "failed": checkpoint.failed_count,
            "states": {
                file_id: {"state": entry.state.value, "changed_at": entry.changed_at.isoformat()}
                for file_id, entry in checkpoint.entries.items()
            },
        }

    def save_indexing_state(self, value: dict[str, object]) -> None:
        """Écrit l'état uniquement dans le même checkpoint que Store et Index."""
        self.save_checkpoint(self._checkpoint_from_legacy_state(value))

    def _load_checkpoint(self) -> MetadataIndexingCheckpoint | None:
        checkpoint = self._index_store.get(self.CHECKPOINT_KEY)
        if checkpoint is None:
            return None
        if not isinstance(checkpoint, MetadataIndexingCheckpoint):
            raise ValueError("The metadata indexing checkpoint is invalid.")
        return checkpoint

    def _upgrade_legacy_index_if_needed(self) -> None:
        """Reconstruit une seule fois les clés par champ des snapshots antérieurs.

        Cette migration travaille sur les champs déjà chargés du projet ; elle
        n'invoque ni provider, ni cache, ni lecture de fichier de preuve.
        """
        if self._index.has_structured_fields:
            return
        for file_id in self._fields_store.keys():
            fields = self._fields_store.get(file_id, ())
            self._index.add(str(file_id), tuple(fields or ()))
        self._index_store.set(self.INDEX_KEY, self._index.snapshot())

    def _transaction_preimage(self, entries: tuple[tuple[str, MetadataResult], ...]) -> dict[str, object]:
        missing = object()
        fields = {}
        for file_id, _result in entries:
            if file_id in fields:
                continue
            previous = self._fields_store.get(file_id, missing)
            fields[file_id] = (previous is not missing, None if previous is missing else previous)
        index_keys = frozenset(self._index_store.keys())
        return {
            "fields": fields,
            "index": (self.INDEX_KEY in index_keys, self._index_store.get(self.INDEX_KEY)),
            "checkpoint": (self.CHECKPOINT_KEY in index_keys, self._index_store.get(self.CHECKPOINT_KEY)),
            "memory_index": self._index,
            "memory_checkpoint": self._checkpoint,
        }

    def _capture_deferred_preimage(self, preimage: Mapping[str, object]) -> None:
        if self._pending_preimage is None:
            self._pending_preimage = dict(preimage)
            return
        fields = self._pending_preimage["fields"]
        incoming = preimage["fields"]
        if not isinstance(fields, dict) or not isinstance(incoming, Mapping):
            raise RuntimeError("Deferred metadata preimage is invalid.")
        for file_id, previous in incoming.items():
            fields.setdefault(file_id, previous)

    def _restore_deferred_preimage(self, preimage: Mapping[str, object], applied: list[str] | None = None) -> None:
        """Restore changed field values and the exact indexed preimage.

        A normal failure is rare, so rebuilding the previous index is confined
        to rollback.  The successful hot path never clones or serialises it.
        """
        fields = preimage["fields"]
        if not isinstance(fields, Mapping):
            raise RuntimeError("Metadata transaction preimage is invalid.")
        for file_id, previous in fields.items():
            existed, value = previous
            if existed:
                self._fields_store.set(str(file_id), value)
            else:
                self._fields_store.delete(str(file_id))
        self._restore_store_value(self.INDEX_KEY, preimage["index"])
        self._restore_store_value(self.CHECKPOINT_KEY, preimage["checkpoint"])
        self._index = MetadataIndex(preimage["index"][1] if preimage["index"][0] else {})
        self._checkpoint = preimage["memory_checkpoint"]

    def _capture_pending_preimage(self, entries: tuple[tuple[str, MetadataResult], ...]) -> None:
        if self._pending_preimage is None:
            self._pending_preimage = self._transaction_preimage(entries)
            return
        fields = self._pending_preimage["fields"]
        if not isinstance(fields, dict):
            raise RuntimeError("PrÃ©image Metadata diffÃ©rÃ©e invalide.")
        existing = frozenset(self._fields_store.keys())
        for file_id, _result in entries:
            if file_id not in fields:
                fields[file_id] = (file_id in existing, self._fields_store.get(file_id))

    def _restore_transaction_preimage(self, preimage: Mapping[str, object]) -> None:
        fields = preimage["fields"]
        if not isinstance(fields, Mapping):
            raise RuntimeError("Préimage de transaction invalide.")
        for file_id, previous in fields.items():
            existed, value = previous
            if existed:
                self._fields_store.set(str(file_id), value)
            else:
                self._fields_store.delete(str(file_id))
        self._restore_store_value(self.INDEX_KEY, preimage["index"])
        self._restore_store_value(self.CHECKPOINT_KEY, preimage["checkpoint"])
        self._index = preimage["memory_index"]
        self._checkpoint = preimage["memory_checkpoint"]

    def _restore_store_value(self, key: str, previous: object) -> None:
        existed, value = previous
        if existed:
            self._index_store.set(key, value)
        else:
            self._index_store.delete(key)

    @staticmethod
    def _checkpoint_from_legacy_state(value: Mapping[str, object]) -> MetadataIndexingCheckpoint:
        try:
            raw_entries = value["states"]
            if not isinstance(raw_entries, Mapping):
                raise ValueError("The indexing states are invalid.")
            entries = {
                str(file_id): MetadataIndexingEntry(
                    str(file_id),
                    MetadataIndexingState(str(raw_entry["state"])),
                    datetime.fromisoformat(str(raw_entry["changed_at"])),
                )
                for file_id, raw_entry in raw_entries.items()
                if isinstance(raw_entry, Mapping)
            }
            if len(entries) != len(raw_entries):
                raise ValueError("The indexing states are invalid.")
            return MetadataIndexingCheckpoint(
                schema_version=int(value["schema_version"]),
                index_version=int(value["index_version"]),
                last_checkpoint_sequence=int(value["last_checkpoint"]),
                total_count=int(value["total"]),
                indexed_count=int(value["indexed"]),
                failed_count=int(value["failed"]),
                entries=entries,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("The legacy metadata indexing state is invalid.") from error

    @property
    def index(self) -> MetadataIndex:
        return self._index
