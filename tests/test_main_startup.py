"""Comportement de démarrage : aucune sélection de dossier implicite."""

from __future__ import annotations

import main as application_main


def test_main_starts_on_home_without_opening_a_directory_dialog(monkeypatch):
    created_windows = []

    class _Application:
        def __init__(self, _arguments) -> None:
            pass

        def setApplicationName(self, _name) -> None:
            pass

        def setOrganizationName(self, _name) -> None:
            pass

        def exec(self) -> int:
            return 0

    class _Window:
        def show(self) -> None:
            created_windows.append(self)

    monkeypatch.setattr(application_main, "QApplication", _Application)
    monkeypatch.setattr(application_main, "MainWindow", _Window)
    monkeypatch.setattr(application_main, "apply_theme", lambda _app: None)
    monkeypatch.setattr(application_main.sys, "argv", ["main.py"])
    monkeypatch.setattr(
        application_main.ReportLoader,
        "load",
        lambda _path: (_ for _ in ()).throw(AssertionError("chargement inattendu")),
    )

    assert application_main.main() == 0
    assert len(created_windows) == 1
