"""Affichage Qt des artefacts déjà classifiés."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

from analysis.artifact_classifier import ArtifactClassifier
from metadata.manager import MetadataManager
from ui.theme import Metrics


class ArtifactsPanel(QGroupBox):
    """Section visuelle sans règle métier propre."""

    def __init__(self, metadata_manager: MetadataManager, classifier: ArtifactClassifier, parent=None) -> None:
        super().__init__("Artefacts détectés", parent)
        self._metadata_manager = metadata_manager
        self._classifier = classifier
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(6)
        self._message = QLabel("Sélectionnez un fichier pour afficher les artefacts.", self)
        self._layout.addWidget(self._message)
        self._badges: list[QLabel] = []

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        self._clear_badges()
        if file_record is None:
            self._message.setText("Sélectionnez un fichier pour afficher les artefacts.")
            return
        metadata = self._metadata_manager.cached_or_stored(file_record)
        if metadata is None:
            self._message.setText("MÃ©tadonnÃ©es en cours d'indexation.")
            return
        artifacts = self._classifier.classify(file_record, metadata)
        if not artifacts:
            self._message.setText("Aucun artefact détecté.")
            return
        self._message.clear()
        for artifact in artifacts:
            badge = QLabel(artifact.label, self)
            badge.setObjectName("artifactBadge")
            badge.setProperty("severity", artifact.severity)
            badge.setContentsMargins(Metrics.PANEL_SPACING, 3, Metrics.PANEL_SPACING, 3)
            self._layout.addWidget(badge)
            self._badges.append(badge)

    def _clear_badges(self) -> None:
        for badge in self._badges:
            self._layout.removeWidget(badge)
            badge.deleteLater()
        self._badges.clear()
