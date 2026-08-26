"""Présentation Qt des événements temporels, sans logique d'extraction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import QFrame, QGroupBox, QLabel, QVBoxLayout, QWidget

from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from ui.theme import Metrics
from ui.widgets.selectable_text_field import SelectableTextField


class TimelinePanel(QGroupBox):
    """Affiche une chronologie ordonnée fournie par le moteur indépendant."""

    def __init__(self, manager: TimelineManager, parent=None) -> None:
        super().__init__("Chronologie", parent)
        self._manager = manager
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(Metrics.PANEL_SPACING)
        self._message = QLabel("Sélectionnez un fichier pour afficher sa chronologie.", self)
        self._message.setWordWrap(True)
        self._layout.addWidget(self._message)
        self._event_widgets: list[QWidget] = []

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        self._clear_events()
        if file_record is None:
            self._message.setText("Sélectionnez un fichier pour afficher sa chronologie.")
            return
        events = self._manager.events_for(file_record)
        if not events:
            self._message.setText("Aucune information chronologique disponible.")
            return
        self._message.clear()
        oldest, newest = events[0].date, events[-1].date
        for index, event in enumerate(events):
            widget = self._event_widget(event, event.date == oldest, event.date == newest)
            self._layout.addWidget(widget)
            self._event_widgets.append(widget)
            if index < len(events) - 1:
                separator = QFrame(self)
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFrameShadow(QFrame.Shadow.Sunken)
                self._layout.addWidget(separator)
                self._event_widgets.append(separator)

    def _event_widget(self, event: TimelineEvent, is_oldest: bool, is_newest: bool) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title = QLabel(f"{event.event_type.icon} {event.event_type.label}", container)
        layout.addWidget(title)
        date_field = SelectableTextField(container)
        date_field.set_value(self._format_date(event.date))
        layout.addWidget(date_field)
        source = QLabel(f"Source : {event.source.label}", container)
        layout.addWidget(source)
        markers = []
        if is_oldest:
            markers.append("Plus ancienne")
        if is_newest:
            markers.append("Plus récente")
        if markers:
            layout.addWidget(QLabel(" • ".join(markers), container))
        if event.is_anomaly and event.comment:
            warning = QLabel(f"⚠ {event.comment}", container)
            warning.setWordWrap(True)
            layout.addWidget(warning)
        return container

    @staticmethod
    def _format_date(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S %z").rstrip() if value.tzinfo else value.strftime("%Y-%m-%d %H:%M:%S")

    def _clear_events(self) -> None:
        for widget in self._event_widgets:
            self._layout.removeWidget(widget)
            widget.deleteLater()
        self._event_widgets.clear()
