"""Exécution asynchrone du pipeline PhotoRec, sans dépendance vers les widgets."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from core.import_progress import ImportProgress
from core.report_loader import ReportLoader


class PhotoRecImportWorker(QObject):
    """Exécute le pipeline et la lecture du rapport hors du thread graphique."""

    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        source_directory: str,
        project_root: Path,
        file_identity_namespace: str | None,
        report_generator: Callable[..., Any],
        report_loader=ReportLoader,
    ) -> None:
        super().__init__()
        self._source_directory = source_directory
        self._project_root = project_root
        self._file_identity_namespace = file_identity_namespace
        self._report_generator = report_generator
        self._report_loader = report_loader

    @Slot()
    def run(self) -> None:
        try:
            self._report_generator(self._source_directory, self._project_root, progress_callback=self._publish_progress)
            self.progress.emit(ImportProgress("open", "Ouverture du projet...", 0, 1))
            report = self._report_loader.load(
                self._project_root,
                file_identity_namespace=self._file_identity_namespace,
            )
            self.progress.emit(ImportProgress("open", "Ouverture du projet...", 1, 1))
            self.completed.emit(report)
        except Exception as error:  # Les erreurs de fichiers sont restituées dans le thread UI.
            self.failed.emit(str(error))
        finally:
            self.finished.emit()

    def _publish_progress(self, *args: object) -> None:
        """Accepte temporairement le callback historique des générateurs injectés par les tests."""
        if len(args) == 1 and isinstance(args[0], ImportProgress):
            self.progress.emit(args[0])
            return
        if len(args) == 2:
            step, message = args
            labels = {1: "scan", 2: "export", 3: "report"}
            self.progress.emit(ImportProgress(labels.get(int(step), "import"), str(message)))
            return
        raise TypeError("Mise à jour de progression PhotoRec invalide.")
