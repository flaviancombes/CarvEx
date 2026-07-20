"""Zone d'aperçu indépendante pour le panneau d'inspection."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ui.theme import Metrics


class PreviewPanel(QFrame):
    """Affiche une image, une première page PDF ou un état adapté au type."""

    IMAGE_MIME_PREFIX = "image/"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._original_pixmap: QPixmap | None = None
        self._pdf_document = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING)
        layout.setSpacing(Metrics.PANEL_SPACING)

        self.heading = QLabel("APERÇU", self)
        self.heading.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.heading)

        self.canvas = QLabel(self)
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumHeight(Metrics.PREVIEW_MIN_HEIGHT)
        self.canvas.setWordWrap(True)
        layout.addWidget(self.canvas)

        self.description = QLabel(self)
        self.description.setWordWrap(True)
        self.description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.description)

        self.clear()

    def clear(self) -> None:
        """Réinitialise l'aperçu lorsqu'aucun fichier n'est sélectionné."""
        self._original_pixmap = None
        self._pdf_document = None
        self.canvas.clear()
        self.canvas.setText("▣")
        self.description.setText("Sélectionnez un fichier pour afficher son aperçu.")

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        """Met à jour l'aperçu à partir des données existantes du rapport."""
        if file_record is None:
            self.clear()
            return

        self._original_pixmap = None
        self._pdf_document = None
        path = self._preview_path(file_record)
        mime = str(file_record.get("mime") or "").lower()

        if mime.startswith(self.IMAGE_MIME_PREFIX) and path:
            self._show_image(path, mime)
        elif mime == "application/pdf" and path:
            self._show_pdf(path)
        elif mime.startswith("audio/"):
            self._show_placeholder("♪", "Audio", f"Type MIME : {mime}\nDurée : non disponible")
        elif mime.startswith("video/"):
            self._show_placeholder("▶", "Vidéo", f"Type MIME : {mime}\nMiniature indisponible")
        else:
            self._show_placeholder(*self._fallback_for(file_record, mime))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._scale_pixmap()

    def _preview_path(self, file_record: Mapping[str, Any]) -> Path | None:
        for field in ("output", "source_path"):
            value = file_record.get(field)
            if value:
                path = Path(str(value))
                if path.is_file():
                    return path
        return None

    def _show_image(self, path: Path, mime: str) -> None:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self._show_placeholder("▧", "Image", f"Aperçu indisponible\nType MIME : {mime}")
            return
        self._original_pixmap = QPixmap.fromImage(image)
        self.description.setText(f"Image — {mime}")
        self._scale_pixmap()

    def _show_pdf(self, path: Path) -> None:
        try:
            from PySide6.QtPdf import QPdfDocument

            document = QPdfDocument(self)
            document.load(str(path))
            if document.pageCount() > 0:
                image = document.render(0, QSize(700, 900))
                if not image.isNull():
                    self._pdf_document = document
                    self._original_pixmap = QPixmap.fromImage(image)
                    self.description.setText("PDF — première page")
                    self._scale_pixmap()
                    return
        except (AttributeError, ImportError, RuntimeError, TypeError):
            pass
        self._show_placeholder(
            "PDF",
            "Document PDF",
            "Aperçu de première page indisponible. L'ouverture externe sera disponible dans une prochaine étape.",
        )

    def _fallback_for(self, file_record: Mapping[str, Any], mime: str) -> tuple[str, str, str]:
        category = str(file_record.get("category") or "Unknown")
        icons = {
            "Documents": "▤",
            "Archives": "▧",
            "Executables": "⚙",
            "Databases": "▦",
            "Code": "</>",
            "Unknown": "?",
        }
        return icons.get(category, "▣"), category, f"Aucun aperçu disponible\nType MIME : {mime or 'inconnu'}"

    def _show_placeholder(self, icon: str, title: str, message: str) -> None:
        self._original_pixmap = None
        self.canvas.clear()
        self.canvas.setText(icon)
        self.description.setText(f"{title}\n{message}")

    def _scale_pixmap(self) -> None:
        if self._original_pixmap is None:
            return
        size = self.canvas.size().boundedTo(QSize(700, 300))
        self.canvas.setPixmap(
            self._original_pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
