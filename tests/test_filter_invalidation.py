from __future__ import annotations

from threading import Event

from PySide6.QtCore import Qt

from models.file_table_model import FileTableModel
from ui.artifact_preloader import _ArtifactPreloadTask
from ui.file_filter_proxy import FileFilterProxyModel
from ui.file_table import FileTable
from utils import performance


class _Artifact:
    def __init__(self, identifier: str) -> None:
        self._identifier = identifier

    def matches(self, identifier: str) -> bool:
        return self._identifier == identifier


class _ArtifactCache:
    def __init__(self) -> None:
        self.entries: dict[str, tuple[_Artifact, ...]] = {}

    def cached_for(self, record):
        return self.entries.get(record["file_id"])


class _CountingProxy(FileFilterProxyModel):
    def __init__(self, artifact_cache) -> None:
        self.invalidations = 0
        self.filter_calls = 0
        super().__init__(artifact_cache)

    def endFilterChange(self, directions) -> None:  # noqa: N802
        self.invalidations += 1
        super().endFilterChange(directions)

    def filterAcceptsRow(self, source_row, source_parent):  # noqa: N802
        self.filter_calls += 1
        return super().filterAcceptsRow(source_row, source_parent)


def _records(count: int = 5) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "file_id": f"{row:08x}-0000-4000-8000-000000000000",
            "name": f"image-{row}.jpg",
            "category": "Images",
        }
        for row in range(count)
    )


def test_artifact_cache_batch_refilters_only_changed_source_rows(qapp):
    records = _records()
    cache = _ArtifactCache()
    model = FileTableModel()
    model.set_records(records)
    proxy = _CountingProxy(cache)
    proxy.setSourceModel(model)
    proxy.set_artifact_filter("image.gps")
    assert proxy.rowCount() == 0

    proxy.invalidations = 0
    proxy.filter_calls = 0
    cache.entries[records[2]["file_id"]] = (_Artifact("image.gps"),)
    proxy.refresh_artifact_rows((records[2]["file_id"],))
    model.refresh_artifact_rows((records[2]["file_id"],))
    qapp.processEvents()

    assert proxy.invalidations == 0
    assert proxy.filter_calls == 1
    assert proxy.rowCount() == 1


def test_artifact_batch_notifies_only_rows_with_new_cache_data(qapp):
    records = _records()
    cache = _ArtifactCache()
    table = FileTable(artifact_cache=cache)
    table.set_files(records)
    table._proxy_model.set_artifact_filter("image.gps")
    assert table.visible_file_count == 0

    cache.entries[records[1]["file_id"]] = (_Artifact("image.gps"),)
    table.refresh_artifact_filter((records[1]["file_id"],))
    qapp.processEvents()

    assert table.visible_file_count == 1


def test_file_table_defers_count_until_the_event_loop(qapp):
    table = FileTable()
    received: list[tuple[str, int]] = []
    table.view_state_changed.connect(lambda category, count: received.append((category, count)))

    table.set_files(_records(2))

    assert received == []
    qapp.processEvents()
    assert received == [("Tous", 2)]


def test_artifact_row_notification_uses_display_role(qapp):
    records = _records(1)
    model = FileTableModel()
    model.set_records(records)
    notifications = []
    model.dataChanged.connect(lambda _first, _last, roles: notifications.append(roles))

    model.refresh_artifact_rows((records[0]["file_id"],))

    assert notifications == [[Qt.ItemDataRole.DisplayRole]]


def test_artifact_preloader_reports_only_newly_cached_file_ids():
    records = _records(3)
    batches: list[tuple[int, tuple[str, ...]]] = []
    signals = type("Signals", (), {})()
    signals.batch_ready = type(
        "BatchReady", (), {"emit": lambda _self, generation, ids: batches.append((generation, ids))}
    )()
    signals.completed = type("Completed", (), {"emit": lambda _self, _generation: None})()
    classifier = type("Classifier", (), {})()
    cached = {records[1]["file_id"]}
    classifier.cached_for = lambda record: () if record["file_id"] in cached else None
    classifier.classify = lambda record, _metadata: cached.add(record["file_id"])
    metadata_manager = type("MetadataManager", (), {"cached_or_stored": lambda _self, _record: object()})()

    _ArtifactPreloadTask(records, metadata_manager, classifier, Event(), 3, signals, 2).run()

    assert batches == [
        (3, (records[0]["file_id"],)),
        (3, (records[2]["file_id"],)),
    ]


def test_idle_metadata_refresh_does_not_enumerate_source_files(qapp, monkeypatch):
    model = FileTableModel()
    model.set_records(_records(2))
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)
    monkeypatch.setattr(model, "file_ids", lambda: (_ for _ in ()).throw(AssertionError("unexpected scan")))

    proxy.refresh_metadata_query()


def test_category_profiling_reports_filter_and_qt_metrics(qapp, monkeypatch, caplog):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level("INFO", logger="carvex.performance")
    model = FileTableModel()
    model.set_records(_records(3))
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_category("Images")
    qapp.processEvents()
    qapp.processEvents()

    message = "\n".join(record.message for record in caplog.records)
    assert "[Catégorie] '' -> 'Images'" in message
    assert "source_rows=3" in message
    assert "filter_calls=" in message
    assert "model_reset=" in message
