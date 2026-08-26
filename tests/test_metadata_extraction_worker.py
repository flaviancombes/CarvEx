from threading import Event

from metadata.base import MetadataCategory, MetadataField
from metadata.indexing import MetadataExtractionWorker, MetadataIndexingService
from metadata.manager import MetadataManager


class Provider:
    provider_id = "test"
    priority = 1

    def supports(self, _record):
        return True

    def extract(self, _record):
        return (MetadataField("general.name", MetadataCategory.GENERAL, "Nom", "ok", source="test"),)


class FailingManager:
    def extract_transient(self, _record):
        raise OSError("corrupted file")


def test_worker_extracts_immutable_batch_without_project_storage():
    service = MetadataIndexingService(("a",))
    batch = service.enqueue(("a",))
    result = MetadataExtractionWorker(MetadataManager((Provider(),)), service, batch, {"a": {"file_id": "a"}}).run()
    assert result.results[0][0] == "a"
    assert service.dequeue_completed() == result


def test_worker_cancellation_and_missing_record_fail_cleanly():
    service = MetadataIndexingService(("a",))
    batch = service.enqueue(("a",))
    cancelled = Event()
    cancelled.set()
    result = MetadataExtractionWorker(MetadataManager((Provider(),)), service, batch, {}, cancelled).run()
    assert result.deferred_ids == ("a",)


def test_worker_marks_unexpected_extraction_failure_without_stopping_the_batch():
    service = MetadataIndexingService(("a",))
    batch = service.enqueue(("a",))

    result = MetadataExtractionWorker(FailingManager(), service, batch, {"a": {"file_id": "a"}}).run()

    assert result.failed_ids == ("a",)
