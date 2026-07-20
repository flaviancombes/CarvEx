"""Point d'entrée de l'interface PySide6 de CarvEx."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from core.report_loader import ReportLoadError, ReportLoader
from ui.main_window import MainWindow
from ui.theme import apply_theme


def _report_directory_from_arguments() -> Path | None:
    """Retourne le dossier de destination fourni à ``main.py``."""
    return Path(sys.argv[1]) if len(sys.argv) > 1 else None


def _choose_report_directory() -> Path | None:
    directory = QFileDialog.getExistingDirectory(
        None,
        "Sélectionner le dossier de destination CarvEx",
    )
    return Path(directory) if directory else None


def main() -> int:
    """Démarre l'UI et charge, si demandé, un rapport existant."""
    app = QApplication([sys.argv[0]])
    app.setApplicationName("CarvEx")
    app.setOrganizationName("CarvEx")
    apply_theme(app)

    window = MainWindow()
    destination = _report_directory_from_arguments() or _choose_report_directory()

    if destination:
        try:
            window.load_report(ReportLoader.load(destination))
        except ReportLoadError as error:
            QMessageBox.warning(window, "Rapport CarvEx introuvable", str(error))

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
