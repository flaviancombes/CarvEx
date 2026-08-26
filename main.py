"""Point d'entrée de l'interface PySide6 de CarvEx."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from core.report_loader import ReportLoader, ReportLoadError
from project.storage import JsonProjectStorage
from ui.main_window import MainWindow
from ui.theme import apply_theme
from utils.performance import measure


def _report_directory_from_arguments() -> Path | None:
    """Retourne le dossier de destination fourni à ``main.py``."""
    return Path(sys.argv[1]) if len(sys.argv) > 1 else None


def main() -> int:
    """Démarre l'UI et charge, si demandé, un rapport existant."""
    app = QApplication([sys.argv[0]])
    app.setApplicationName("CarvEx")
    app.setOrganizationName("CarvEx")
    apply_theme(app)

    window = MainWindow()
    destination = _report_directory_from_arguments()

    if destination:
        if JsonProjectStorage.exists(destination):
            window._open_recent_project(str(destination))
        else:
            try:
                with measure("report.open", destination=destination):
                    report = ReportLoader.load(destination)
                with measure("ui.report_bind", files=len(report.files)):
                    window.load_report(report)
            except ReportLoadError as error:
                QMessageBox.warning(window, "Rapport CarvEx introuvable", str(error))

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
