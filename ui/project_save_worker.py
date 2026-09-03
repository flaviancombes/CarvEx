"""Worker dédié au flush disque d'un projet déjà figé par le thread Qt."""

from __future__ import annotations

import logging
from threading import current_thread

from PySide6.QtCore import QObject, Signal, Slot

from project.repository import ProjectRepository
from utils.performance import ENABLED

LOGGER = logging.getLogger("carvex.performance")


class ProjectSaveWorker(QObject):
    """Exécute uniquement ``ProjectRepository.flush`` hors du thread Qt."""

    phase = Signal(str)
    succeeded = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, repository: ProjectRepository) -> None:
        super().__init__()
        self._repository = repository

    @Slot()
    def run(self) -> None:
        try:
            if ENABLED:
                LOGGER.info("[Save] background flush started thread=%s", current_thread().name)
            self._repository.flush(self._publish_phase)
        except Exception as error:  # the UI must retain the project on a failed flush
            LOGGER.exception("[Save] background flush failed")
            self.failed.emit(str(error) or type(error).__name__)
        else:
            if ENABLED:
                LOGGER.info("[Save] background flush completed")
            self.succeeded.emit()
        finally:
            self.finished.emit()

    def _publish_phase(self, phase: str) -> None:
        if ENABLED:
            LOGGER.info("[Save] background flush phase=%s", phase)
        self.phase.emit(phase)
