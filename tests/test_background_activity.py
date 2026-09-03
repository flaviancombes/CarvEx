"""Couverture du registre global d'activité et de son raccordement Timeline."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.service import TimelineService
from timeline.source import FILE_MODIFIED, FILESYSTEM
from ui.background_activity import BackgroundActivityIndicator, BackgroundTaskRegistry
from ui.project_session_controller import ProjectSessionController
from ui.timeline_view import TimelineView


def test_background_registry_and_indicator_track_multiple_tasks(qtbot) -> None:
    registry = BackgroundTaskRegistry()
    indicator = BackgroundActivityIndicator(registry)
    qtbot.addWidget(indicator)

    assert registry.is_ready
    assert indicator.label.text() == "Prêt"
    assert indicator.progress.isHidden()

    registry.start_task("timeline", "Construction de la Timeline", total=100)
    registry.update_task("timeline", current=68)

    assert not registry.is_ready
    assert "Construction de la Timeline" in indicator.label.text()
    assert indicator.progress.maximum() == 100
    assert indicator.progress.value() == 68

    registry.start_task("metadata", "Indexation des métadonnées", total=20)
    registry.finish_task("timeline")

    assert not registry.is_ready
    assert "Indexation des métadonnées" in indicator.label.text()

    registry.set_phase("metadata", "Finalisation de l’indexation des métadonnées…")

    assert indicator.progress.minimum() == 0
    assert indicator.progress.maximum() == 0

    registry.finish_task("metadata")

    assert registry.is_ready
    assert indicator.label.text() == "Prêt"
    assert indicator.progress.isHidden()


def test_cancelled_or_stale_task_cannot_keep_activity_visible(qtbot) -> None:
    registry = BackgroundTaskRegistry()
    indicator = BackgroundActivityIndicator(registry)
    qtbot.addWidget(indicator)
    registry.start_task("timeline", "Construction de la Timeline", total=10)

    registry.finish_all(cancelled=True)
    registry.update_task("timeline", current=10)

    assert registry.is_ready
    assert indicator.label.text() == "Prêt"


def test_timeline_reports_construction_then_finalization_until_projection_is_done(qtbot) -> None:
    class _Extractor:
        def extract(self, _record):
            return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM),)

    registry = BackgroundTaskRegistry()
    changes: list[tuple[str, str]] = []
    registry.tasks_changed.connect(
        lambda tasks: changes.append((tasks[-1].task_id, tasks[-1].label)) if tasks else changes.append(("", "Prêt"))
    )
    service = TimelineService(TimelineManager((_Extractor(),)))
    service.set_records(
        tuple({"file_id": str(UUID(int=index + 1)), "name": f"file-{index}.jpg"} for index in range(5_000))
    )
    view = TimelineView(service, background_tasks=registry)
    qtbot.addWidget(view)

    view.load_events()

    assert registry.task("timeline") is not None
    assert registry.task("timeline").total == 5_000
    qtbot.waitUntil(lambda: registry.task("timeline") is None, timeout=10_000)

    labels = [label for _task_id, label in changes]
    assert "Construction de la Timeline" in labels
    assert "Finalisation de la Timeline…" in labels
    assert labels[-1] == "Prêt"
    # Trois lots source de 2 048 preuves, pas une mise à jour par preuve.
    assert len(changes) < 12


def test_timeline_reset_removes_activity_and_ignores_late_worker_progress(qtbot) -> None:
    registry = BackgroundTaskRegistry()
    service = TimelineService(TimelineManager(()))
    view = TimelineView(service, background_tasks=registry)
    qtbot.addWidget(view)
    view._build_generation = 4
    registry.start_task("timeline", "Construction de la Timeline", total=10)

    view.reset_events()
    view._update_build_progress(4, 10)

    assert registry.task("timeline") is None


def test_metadata_indexing_registers_known_progress_without_polling_new_workers() -> None:
    class _Indexing:
        is_running = True
        progress = SimpleNamespace(total=200, indexed=80, failed=5)

        def start(self, _records, _manager) -> None:
            return None

    registry = BackgroundTaskRegistry()
    controller = object.__new__(ProjectSessionController)
    controller._metadata_indexing = _Indexing()
    controller._metadata_manager = SimpleNamespace(set_store_writable=lambda _value: None)
    controller._metadata_timer = SimpleNamespace(start=lambda: None)
    controller._background_tasks = registry
    controller._show_metadata_progress = lambda: None

    controller._start_metadata_indexing(())

    task = registry.task("metadata")
    assert task is not None
    assert task.current == 85
    assert task.total == 200
