"""Non-régression de l'indication de progression lors d'un import PhotoRec."""

from __future__ import annotations

from threading import Event

from PySide6.QtWidgets import QApplication

import ui.main_window as main_window_module
from ui.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication(["carvex-test", "-platform", "offscreen"])


def test_photorec_import_reports_each_pipeline_step_without_blocking_the_ui(tmp_path, monkeypatch, qtbot):
    _application()
    dialogs = []

    class _ProgressDialog:
        def __init__(self, label, _cancel, minimum, maximum, _parent) -> None:
            self.labels = [label]
            self.values = [minimum]
            self.maximum = maximum
            self.closed = False
            dialogs.append(self)

        def setWindowTitle(self, _title) -> None:
            pass

        def setWindowModality(self, _modality) -> None:
            pass

        def setCancelButton(self, _button) -> None:
            pass

        def setAutoClose(self, _enabled) -> None:
            pass

        def setAutoReset(self, _enabled) -> None:
            pass

        def setMinimumDuration(self, _duration) -> None:
            pass

        def setRange(self, _minimum, maximum) -> None:
            self.maximum = maximum

        def show(self) -> None:
            pass

        def setValue(self, value) -> None:
            self.values.append(value)

        def setLabelText(self, label) -> None:
            self.labels.append(label)

        def close(self) -> None:
            self.closed = True

    callbacks = []
    worker_started = Event()
    release_worker = Event()

    def generate(_source, _destination, *, progress_callback) -> None:
        callbacks.append(progress_callback)
        progress_callback(1, "Analyse des fichiers...")
        worker_started.set()
        assert release_worker.wait(2)
        progress_callback(2, "Export des fichiers...")
        progress_callback(3, "Génération du rapport...")

    loaded = []
    monkeypatch.setattr(main_window_module, "QProgressDialog", _ProgressDialog)
    monkeypatch.setattr(main_window_module, "generate_photorec_report", generate)
    window = MainWindow()
    window._projects._report_loader = type("Loader", (), {"load": staticmethod(lambda *_args, **_kwargs: object())})
    window._projects._load_report = lambda report, update_metadata: loaded.append((report, update_metadata))

    window._import_photo_rec_directory("C:/PhotoRec", tmp_path / "Beta.carvex")
    qtbot.waitUntil(worker_started.is_set)
    window.setWindowTitle("CarvEx responsive")
    assert window.windowTitle() == "CarvEx responsive"
    release_worker.set()
    qtbot.waitUntil(lambda: bool(loaded))

    assert callbacks
    assert "Analyse des fichiers..." in dialogs[0].labels
    assert "Export des fichiers..." in dialogs[0].labels
    assert "Génération du rapport..." in dialogs[0].labels
    assert "Ouverture du projet...\n1 / 1 fichiers" in dialogs[0].labels
    assert dialogs[0].closed
    assert loaded == [(loaded[0][0], True)]
