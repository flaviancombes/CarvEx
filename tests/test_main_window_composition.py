"""Non-régressions de la composition UI de la fenêtre principale."""

from __future__ import annotations

from uuid import uuid4

from PySide6.QtWidgets import QApplication

from ui.application_navigation import ApplicationNavigationController, EvidenceWorkflowController
from ui.main_window import MainWindow
from ui.project_session_controller import ProjectSessionController
from ui.project_workflow_controller import ProjectWorkflowController


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def test_main_window_composes_dedicated_ui_controllers():
    _application()
    window = MainWindow()

    assert isinstance(window._navigation, ApplicationNavigationController)
    assert isinstance(window._evidence, EvidenceWorkflowController)
    assert isinstance(window._projects, ProjectWorkflowController)
    assert isinstance(window._session, ProjectSessionController)


def test_legacy_evidence_slot_delegates_to_the_shared_workflow(monkeypatch):
    _application()
    window = MainWindow()
    record = {"file_id": str(uuid4()), "name": "preuve.jpg"}
    calls = []
    monkeypatch.setattr(window._evidence, "add_file", lambda value: calls.append(value))

    window._add_file_to_investigation(record)

    assert calls == [record]
