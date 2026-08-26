"""Assistant minimal de création de projet, sans logique métier de projet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class NewProjectDialog(QDialog):
    def __init__(self, photo_rec_directory: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nouveau projet CarvEx")
        self.name_field = QLineEdit(self)
        self.location_field = QLineEdit(self)
        initial_import_directory = "" if photo_rec_directory is None else photo_rec_directory
        self.import_field = QLineEdit(initial_import_directory, self)
        self.description_field = QTextEdit(self)
        self.description_field.setMaximumHeight(90)
        form = QFormLayout()
        form.addRow("Nom du projet", self.name_field)
        form.addRow("Emplacement", self._path_row(self.location_field, self._choose_location))
        form.addRow("Dossier PhotoRec", self._path_row(self.import_field, self._choose_import))
        form.addRow("Description", self.description_field)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @property
    def project_root(self) -> Path:
        name = self.name_field.text().strip()
        return Path(self.location_field.text().strip()) / f"{name}.carvex"

    def _path_row(self, field: QLineEdit, choose) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(field)
        button = QPushButton("Parcourir…", self)
        button.clicked.connect(choose)
        layout.addWidget(button)
        return layout

    def _choose_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Emplacement du projet")
        if directory:
            self.location_field.setText(directory)

    def _choose_import(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Dossier PhotoRec à importer")
        if directory:
            self.import_field.setText(directory)
