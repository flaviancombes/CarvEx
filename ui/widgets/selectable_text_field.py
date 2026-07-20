"""Champ de métadonnée long, lisible et copiable naturellement."""

from __future__ import annotations

from math import ceil

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QTextEdit

from ui.theme import Metrics


class SelectableTextField(QTextEdit):
    """Texte multi-ligne en lecture seule avec sélection et menu natif Qt."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setAcceptRichText(False)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(Metrics.TEXT_FIELD_MIN_HEIGHT)

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
        self.setFixedHeight(
            max(
                Metrics.TEXT_FIELD_MIN_HEIGHT,
                height + margins.top() + margins.bottom() + Metrics.TEXT_FIELD_EXTRA_HEIGHT,
            )
        )
