"""Panneau droit d'inspection d'un fichier sélectionné."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.preview_panel import PreviewPanel
from ui.metadata_panel import MetadataPanel
from ui.theme import Metrics
from ui.widgets.selectable_text_field import SelectableTextField


class DetailsPanel(QScrollArea):
    """Panneau d'aperçu et de métadonnées organisé en sections DFIR."""

    SECTIONS = (
        ("Informations", (("name", "Nom du fichier"), ("category", "Catégorie"), ("mime", "Type MIME"), ("size", "Taille"))),
        ("Intégrité", (("sha256", "SHA-256"),)),
        ("Emplacements", (("output", "Chemin exporté"), ("source_path", "Chemin PhotoRec"), ("source_directory", "Dossier PhotoRec"))),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("detailsPanel")
        self.setWidgetResizable(True)

        content = QWidget(self)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(Metrics.PANEL_MARGIN, Metrics.PANEL_MARGIN, Metrics.PANEL_MARGIN, Metrics.PANEL_MARGIN)
        self.content_layout.setSpacing(Metrics.PANEL_SPACING)

        self.title = QLabel("Aucun fichier sélectionné", content)
        self.title.setObjectName("detailsTitle")
        self.title.setWordWrap(True)
        self.content_layout.addWidget(self.title)

        preview_section = QGroupBox("Aperçu", content)
        preview_layout = QVBoxLayout(preview_section)
        preview_layout.setContentsMargins(Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING)
        self.preview_panel = PreviewPanel(preview_section)
        preview_layout.addWidget(self.preview_panel)
        self.content_layout.addWidget(preview_section)

        self._fields: dict[str, SelectableTextField] = {}
        for section_title, fields in self.SECTIONS:
            self.content_layout.addWidget(self._create_section(section_title, fields, content))

        self.metadata_panel = MetadataPanel(parent=content)
        self.content_layout.addWidget(self.metadata_panel)

        # Réservé aux futures sections : EXIF, timeline, VirusTotal, hex viewer, etc.
        self.content_layout.addStretch()
        self.setWidget(content)

    def _create_section(self, title: str, fields: Sequence[tuple[str, str]], parent: QWidget) -> QGroupBox:
        section = QGroupBox(title, parent)
        form = QFormLayout(section)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(Metrics.PANEL_SPACING)
        for field, label in fields:
            value_field = SelectableTextField(section)
            self._fields[field] = value_field
            form.addRow(label, value_field)
        return section

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        """Met à jour l'aperçu et les métadonnées existantes du rapport."""
        self.preview_panel.set_file(file_record)
        self.metadata_panel.set_file(file_record)
        if file_record is None:
            self.title.setText("Aucun fichier sélectionné")
            for field in self._fields.values():
                field.set_value(None)
            return

        self.title.setText(str(file_record.get("name") or "Sans nom"))
        for name, field in self._fields.items():
            field.set_value(file_record.get(name))
