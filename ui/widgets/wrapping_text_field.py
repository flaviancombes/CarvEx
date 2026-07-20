"""Champ texte en lecture seule, sélectionnable et à hauteur adaptative."""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QPlainTextEdit


class WrappingTextField(QPlainTextEdit):
    """Affiche intégralement une valeur longue sans la tronquer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(28)

    def set_value(self, value: object) -> None:
        self.setPlainText("—" if value is None or value == "" else str(value))
        QTimer.singleShot(0, self._adjust_height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._adjust_height()

    def _adjust_height(self) -> None:
        document = self.document()
        document.setTextWidth(max(1, self.viewport().width()))
        height = ceil(document.documentLayout().documentSize().height())
        margins = self.contentsMargins()
        self.setFixedHeight(max(28, height + margins.top() + margins.bottom() + 8))
