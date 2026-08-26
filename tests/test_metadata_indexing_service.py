import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from metadata.base import MetadataResult
from metadata.indexing import (
    MetadataBatchResult,
    MetadataIndexingCheckpoint,
    MetadataIndexingEntry,
    MetadataIndexingService,
    MetadataIndexingState,
)
from metadata.manager import MetadataManager


class _Provider:
    provider_id = "indexing-test"
    priority = 1

    def __init__(self) -> None:
        self.calls: list[str] = []

    def supports(self, _record) -> bool:
        return True

    def extract(self, record):
        self.calls.append(record["file_id"])
        return ()


class _GeneratedRecords(Sequence[dict[str, object]]):
    def __init__(self, count: int) -> None:
        self._count = count

    def __len__(self) -> int:
        return self._count

    def __getitem__(self, index: int) -> dict[str, object]:
        if not 0 <= index < self._count:
            raise IndexError(index)
        return {"file_id": f"file-{index}", "category": "Images"}

    def __iter__(self) -> Iterator[dict[str, object]]:
        for index in range(self._count):
            yield self[index]


def test_fifo_state_transitions_and_progress():
    service = MetadataIndexingService(("a", "b", "c"))
    first = service.enqueue(("a", "b"))
    second = service.enqueue(("c",))
    assert service.dequeue() == first
    assert service.dequeue() == second
    service.complete(MetadataBatchResult(first, (("a", MetadataResult()),), ("b",)))
    assert service.state_for("a") is MetadataIndexingState.INDEXED
    assert service.state_for("b") is MetadataIndexingState.FAILED
    assert service.progress.percentage == 200 / 3


def test_batches_are_immutable_and_reject_invalid_transitions():
    service = MetadataIndexingService(("a",))
    batch = service.enqueue(("a",))
    assert batch.file_ids == ("a",)
    try:
        service.enqueue(("a",))
    except ValueError:
        pass
    else:
        raise AssertionError("Une seconde planification est invalide.")


def test_service_hydrates_all_states_dates_and_counters_without_scheduling():
    changed_at = datetime(2026, 8, 2, 12, 30, tzinfo=UTC)
    checkpoint = MetadataIndexingCheckpoint(
        1,
        3,
        7,
        3,
        1,
        1,
        {
            "indexed": MetadataIndexingEntry("indexed", MetadataIndexingState.INDEXED, changed_at),
            "failed": MetadataIndexingEntry("failed", MetadataIndexingState.FAILED, changed_at),
            "pending": MetadataIndexingEntry("pending", MetadataIndexingState.NOT_INDEXED, changed_at),
        },
    )

    service = MetadataIndexingService.from_checkpoint(checkpoint)

    assert service.progress.total == 3
    assert service.progress.indexed == 1
    assert service.progress.failed == 1
    assert service.state_for("indexed") is MetadataIndexingState.INDEXED
    assert service.state_for("failed") is MetadataIndexingState.FAILED
    assert service.state_for("pending") is MetadataIndexingState.NOT_INDEXED
    assert service.changed_at_for("indexed") == changed_at
    assert service.persistence_snapshot()["states"]["indexed"]["changed_at"] == changed_at.isoformat()
    assert service.dequeue() is None
    assert service.dequeue_completed() is None


def test_service_uses_default_not_indexed_state_without_a_checkpoint():
    service = MetadataIndexingService.from_checkpoint(None, ("file-a", "file-b"))

    assert service.state_for("file-a") is MetadataIndexingState.NOT_INDEXED
    assert service.state_for("file-b") is MetadataIndexingState.NOT_INDEXED
    assert service.progress.total == 2
    assert service.progress.indexed == 0
    assert service.dequeue() is None


def test_async_indexing_skips_indexed_and_failed_records_and_normalizes_interrupted_ones():
    changed_at = datetime(2026, 8, 3, 12, tzinfo=UTC)
    checkpoint = MetadataIndexingCheckpoint(
        1,
        1,
        2,
        3,
        1,
        1,
        {
            "indexed": MetadataIndexingEntry("indexed", MetadataIndexingState.INDEXED, changed_at),
            "failed": MetadataIndexingEntry("failed", MetadataIndexingState.FAILED, changed_at),
            "interrupted": MetadataIndexingEntry("interrupted", MetadataIndexingState.INDEXING, changed_at),
        },
    )
    provider = _Provider()
    service = MetadataIndexingService.from_checkpoint(checkpoint)
    records = [
        {"file_id": "indexed"},
        {"file_id": "failed"},
        {"file_id": "interrupted"},
        {"file_id": "new"},
    ]

    service.start(records, MetadataManager((provider,)), batch_size=1)
    _drain_service(service)

    assert provider.calls == ["interrupted", "new"]
    assert service.state_for("indexed") is MetadataIndexingState.INDEXED
    assert service.state_for("failed") is MetadataIndexingState.FAILED
    assert service.state_for("interrupted") is MetadataIndexingState.INDEXED
    assert service.state_for("new") is MetadataIndexingState.INDEXED
    assert service.progress.indexed == 3
    assert service.progress.failed == 1
    assert service.progress.percentage == 100.0
    assert service.progress.items_per_second >= 0.0


def test_cancellation_returns_unfinished_records_to_not_indexed():
    service = MetadataIndexingService(("a", "b"))
    batch = service.enqueue(("a", "b"))
    result = MetadataBatchResult(batch, (), (), ("a", "b"))

    service.complete(result)

    assert service.state_for("a") is MetadataIndexingState.NOT_INDEXED
    assert service.state_for("b") is MetadataIndexingState.NOT_INDEXED


def test_completed_results_are_fifo_and_do_not_duplicate_a_file():
    service = MetadataIndexingService(("a", "b"))
    first = service.enqueue(("a",))
    second = service.enqueue(("b",))
    service.submit(MetadataBatchResult(first, (("a", MetadataResult()),)))
    service.submit(MetadataBatchResult(second, (("b", MetadataResult()),)))

    assert tuple(result.batch.sequence for result in service.collect_completed()) == (0, 1)
    assert service.state_for("a") is MetadataIndexingState.INDEXING
    assert service.state_for("b") is MetadataIndexingState.INDEXING


def test_large_record_catalogues_are_registered_without_queue_growth():
    provider = _Provider()
    service = MetadataIndexingService()
    records = _GeneratedRecords(100_000)

    service.start(records, MetadataManager((provider,)), batch_size=1, max_workers=1)
    service.cancel()
    service.shutdown()

    assert service.progress.total == 100_000
    assert service.progress.indexing <= 1


def test_300000_record_catalogue_keeps_only_configured_batches_in_flight():
    provider = _Provider()
    service = MetadataIndexingService()
    records = _GeneratedRecords(300_000)

    service.start(records, MetadataManager((provider,)), batch_size=8, max_workers=1)
    service.cancel()
    service.shutdown()

    assert service.progress.total == 300_000
    assert service.progress.indexing <= 8


def _drain_service(service: MetadataIndexingService) -> None:
    deadline = time.monotonic() + 5
    while service.is_running or service.has_completed:
        for result in service.collect_completed():
            service.complete(result)
        service.schedule_workers()
        if time.monotonic() > deadline:
            raise AssertionError("L'indexation asynchrone n'a pas terminé.")
        time.sleep(0.001)
