"""Régressions : un batch Investigation ne rafraîchit jamais tout le corpus Qt."""

from __future__ import annotations

import pytest

from investigation.module import InvestigationProjectModule
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from ui.application_navigation import EvidenceWorkflowController


class _Panel:
    def __init__(self, service: InvestigationService) -> None:
        self.service = service

    def edit_evidence(self, _target, **_kwargs) -> object:
        return object()


class _Tabs:
    def __init__(self) -> None:
        self.current_index: int | None = None

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - contrat Qt simulé
        self.current_index = index


class _Projection:
    def __init__(self) -> None:
        self.refreshed: list[tuple[str, ...]] = []
        self.lookup_calls = 0

    def refresh_investigation_markers(self, file_ids) -> None:
        self.refreshed.append(tuple(file_ids))

    def set_investigation_presence_lookup(self, _lookup) -> None:
        self.lookup_calls += 1


def _controller() -> tuple[EvidenceWorkflowController, InvestigationService, _Projection, _Projection, list[bool]]:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Bulk UI"))
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    timeline = _Projection()
    bookmarks = _Projection()
    dirty: list[bool] = []
    controller = EvidenceWorkflowController(
        entity_resolver=None,  # type: ignore[arg-type]
        investigation_panel=_Panel(service),
        timeline_view=timeline,
        bookmarks_view=bookmarks,
        tabs=_Tabs(),
        status_message=lambda _message: None,
        persistent_change=lambda: dirty.append(True),
        refresh_file_markers=lambda _file_ids: None,
        refresh_timeline_markers=timeline.refresh_investigation_markers,
        refresh_bookmark_markers=bookmarks.refresh_investigation_markers,
    )
    return controller, service, timeline, bookmarks, dirty


@pytest.mark.parametrize("count", (1, 5, 50, 500))
def test_bulk_add_uses_one_event_and_only_targeted_projection_refreshes(count: int):
    controller, service, timeline, bookmarks, dirty = _controller()
    received = []
    assert service.event_bus is not None
    service.event_bus.subscribe(received.append)
    file_ids = tuple(f"file-{index}" for index in range(count))

    controller.add_files_bulk(file_ids)

    assert len(service.list_items()) == count
    assert len(received) == 1
    assert timeline.refreshed == [file_ids]
    assert bookmarks.refreshed == [file_ids]
    assert timeline.lookup_calls == 0
    assert bookmarks.lookup_calls == 0
    assert dirty == [True]


def test_bulk_add_is_idempotent_and_preserves_targeted_notifications():
    controller, service, timeline, bookmarks, _dirty = _controller()
    file_ids = tuple(f"file-{index}" for index in range(5))

    controller.add_files_bulk(file_ids)
    controller.add_files_bulk(file_ids)

    assert len(service.list_items()) == len(file_ids)
    assert timeline.refreshed == [file_ids, file_ids]
    assert bookmarks.refreshed == [file_ids, file_ids]


def test_single_evidence_refreshes_only_its_canonical_file_markers():
    controller, _service, timeline, bookmarks, _dirty = _controller()

    controller._edit(
        InvestigationTargetRef("file", "file-1"),
        original_name="one.jpg",
    )

    assert timeline.refreshed == [("file-1",)]
    assert bookmarks.refreshed == [("file-1",)]
    assert timeline.lookup_calls == 0
    assert bookmarks.lookup_calls == 0
