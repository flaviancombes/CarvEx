"""Dialogue modal non annulable pendant une sauvegarde de projet."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout, QWidget


class ProjectSaveDialog(QDialog):
    """Rend visible une opération de sauvegarde dont la durée est inconnue."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sauvegarde du projet")
        self.setModal(True)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        self._message = QLabel("Sauvegarde du projet en cours…", self)
        self._phase = QLabel("Préparation…", self)
        self._warning = QLabel("Veuillez patienter. Ne fermez pas CarvEx pendant la sauvegarde.", self)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        layout.addWidget(self._message)
        layout.addWidget(self._phase)
        layout.addWidget(self._warning)
        layout.addWidget(self._progress)

    def set_phase(self, phase: str) -> None:
        self._phase.setText(phase)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        event.ignore()
