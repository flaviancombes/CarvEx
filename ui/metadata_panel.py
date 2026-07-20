"""Présentation Qt des métadonnées extraites à la demande."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from metadata.base import MetadataResult
from metadata.manager import MetadataManager, build_default_manager
from ui.theme import Metrics
from ui.widgets.selectable_text_field import SelectableTextField


class MetadataPanel(QGroupBox):
    """Section autonome qui déclenche l'extraction seulement sur sélection."""

    def __init__(self, manager: MetadataManager | None = None, parent=None) -> None:
        super().__init__("Métadonnées", parent)
        self._manager = manager or build_default_manager()
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(Metrics.PANEL_SPACING)

        self.indicators = QLabel(self)
        self.indicators.setWordWrap(True)
        self._layout.addWidget(self.indicators)

        self.message = QLabel("Sélectionnez un fichier pour afficher ses métadonnées.", self)
        self.message.setWordWrap(True)
        self._layout.addWidget(self.message)
        self._groups: list[QGroupBox] = []

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        """Affiche le résultat du gestionnaire pour le fichier sélectionné."""
        self._clear_groups()
        if file_record is None:
            self.indicators.clear()
            self.message.setText("Sélectionnez un fichier pour afficher ses métadonnées.")
            return

        result = self._manager.extract(file_record)
        self._render_result(result)

    def _render_result(self, result: MetadataResult) -> None:
        self.indicators.setText("  ".join(result.indicators))
        if result.unavailable_message:
            self.message.setText(result.unavailable_message)
            return

        self.message.clear()
        for group in result.groups:
            section = QGroupBox(group.title, self)
            form = QFormLayout(section)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setVerticalSpacing(Metrics.PANEL_SPACING)
            for item in group.items:
                value = SelectableTextField(section)
                value.set_value(item.value)
                form.addRow(item.label, value)
            self._layout.addWidget(section)
            self._groups.append(section)

    def _clear_groups(self) -> None:
        for section in self._groups:
            self._layout.removeWidget(section)
            section.deleteLater()
        self._groups.clear()
