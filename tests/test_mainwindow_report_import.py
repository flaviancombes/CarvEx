"""Intégration du flux de création de projet avec import PhotoRec."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

import ui.main_window as main_window_module
from ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def _write_photorec_file(root: Path) -> None:
    (root / "recup.jpg").write_bytes(b"\xff\xd8\xffCarvEx test image")


def test_new_project_scans_exports_generates_and_loads_photorec_report(tmp_path, monkeypatch, qtbot):
    """Le flux Qt produit le rapport avant de le charger dans la vue Fichiers."""
    _application()
    report_root = tmp_path / "photorec-output"
    report_root.mkdir()
    _write_photorec_file(report_root)
    project_root = tmp_path / "Beta.carvex"

    class _Field:
        def __init__(self, value: str) -> None:
            self._value = value

        def text(self) -> str:
            return self._value

        def toPlainText(self) -> str:
            return self._value

    class _Dialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, photo_rec_directory: str | None, _parent) -> None:
            assert photo_rec_directory == str(report_root)
            self.name_field = _Field("Beta")
            self.location_field = _Field(str(tmp_path))
            self.import_field = _Field(photo_rec_directory or "")
            self.description_field = _Field("")

        @property
        def project_root(self) -> Path:
            return project_root

        def exec(self) -> int:
            return self.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "NewProjectDialog", _Dialog)
    window = MainWindow()

    window._new_project(str(report_root))
    qtbot.waitUntil(lambda: window.file_table.file_count == 1)

    assert window.project_manager.active_project is not None
    assert window.file_table.file_count == 1
    assert (project_root / "reports" / "index.html").is_file()
    assert (project_root / "Images" / "JPEG" / "recup.jpg").is_file()
    assert window.project_manager.active_project.metadata.source_reference == str(
        project_root / "reports" / "index.html"
    )

    window.investigation_panel.detach()
    window.project_manager.close_project()
