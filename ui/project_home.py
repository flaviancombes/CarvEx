"""Écran d'accueil affiché lorsqu'aucun projet n'est actif."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget


class ProjectHome(QWidget):
    new_requested = Signal()
    open_requested = Signal()
    import_requested = Signal()
    recent_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        title = QLabel("CarvEx", self)
        title.setObjectName("detailsTitle")
        subtitle = QLabel("Ouvrez ou créez un projet d'investigation.", self)
        self.new_button = QPushButton("Nouveau projet…", self)
        self.open_button = QPushButton("Ouvrir un projet…", self)
        self.import_button = QPushButton("Importer un dossier PhotoRec…", self)
        self.recent = QListWidget(self)
        self.recent.itemActivated.connect(lambda item: self.recent_requested.emit(item.data(256)))
        self.new_button.clicked.connect(self.new_requested)
        self.open_button.clicked.connect(self.open_requested)
        self.import_button.clicked.connect(self.import_requested)
        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(self.new_button)
        layout.addWidget(self.open_button)
        layout.addWidget(self.import_button)
        layout.addSpacing(16)
        layout.addWidget(QLabel("Projets récents", self))
        layout.addWidget(self.recent)
        layout.addStretch()

    def set_recents(self, paths: list[str]) -> None:
        self.recent.clear()
        for path in paths:
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(path, self.recent)
            item.setData(256, path)
