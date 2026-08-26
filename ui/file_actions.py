"""Actions utilisateur Windows appliquées à un fichier de rapport."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget


class FileActions(QObject):
    """Point d'extension unique pour les actions du menu et des raccourcis."""

    status_message = Signal(str)

    def open_file(self, file_record: Mapping[str, Any], parent: QWidget) -> None:
        """Ouvre le fichier exporté avec l'application par défaut de Windows."""
        path = self._existing_file(file_record, "output", parent, "Fichier exporté")
        if path is None:
            return
        try:
            os.startfile(str(path))
        except OSError as error:
            self._show_error(parent, "Ouverture impossible", f"Windows ne peut pas ouvrir ce fichier.\n\n{error}")
            return
        self.status_message.emit("Fichier ouvert.")

    def open_containing_folder(self, file_record: Mapping[str, Any], parent: QWidget) -> None:
        """Ouvre l'Explorateur Windows et sélectionne le fichier exporté."""
        path = self._existing_file(file_record, "output", parent, "Fichier exporté")
        if path is None:
            return
        if not path.parent.is_dir():
            self._show_error(
                parent, "Dossier introuvable", f"Le dossier contenant le fichier n'existe plus.\n\n{path.parent}"
            )
            return
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError as error:
            self._show_error(parent, "Explorateur indisponible", f"Windows ne peut pas ouvrir ce dossier.\n\n{error}")
            return
        self.status_message.emit("Dossier ouvert.")

    def copy_value(self, file_record: Mapping[str, Any], field: str, label: str) -> None:
        """Place une valeur existante du rapport dans le presse-papiers Qt."""
        value = file_record.get(field)
        if value is None or value == "":
            self.status_message.emit(f"{label} indisponible.")
            return
        QApplication.clipboard().setText(str(value))
        self.status_message.emit(f"{label} copié.")

    def create_context_menu(self, file_record: Mapping[str, Any], parent: QWidget) -> QMenu:
        """Construit le menu d'actions, extensible pour les futures analyses."""
        menu = QMenu(parent)
        menu.addAction("📂 Ouvrir", lambda: self.open_file(file_record, parent))
        menu.addAction(
            "📁 Ouvrir le dossier contenant le fichier", lambda: self.open_containing_folder(file_record, parent)
        )
        menu.addSeparator()
        menu.addAction("📋 Copier le SHA-256", lambda: self.copy_value(file_record, "sha256", "SHA-256"))
        menu.addAction("📋 Copier le chemin exporté", lambda: self.copy_value(file_record, "output", "Chemin exporté"))
        menu.addAction(
            "📋 Copier le chemin PhotoRec", lambda: self.copy_value(file_record, "source_path", "Chemin PhotoRec")
        )
        menu.addAction("📋 Copier le nom du fichier", lambda: self.copy_value(file_record, "name", "Nom du fichier"))
        return menu

    def _existing_file(
        self,
        file_record: Mapping[str, Any],
        field: str,
        parent: QWidget,
        label: str,
    ) -> Path | None:
        value = file_record.get(field)
        path = Path(str(value)) if value else None
        if path is None or not path.is_file():
            display_path = str(path) if path else "Chemin indisponible"
            self._show_error(
                parent, f"{label} introuvable", f"Le fichier n'existe plus ou n'est plus accessible.\n\n{display_path}"
            )
            return None
        return path

    @staticmethod
    def _show_error(parent: QWidget, title: str, message: str) -> None:
        QMessageBox.warning(parent, title, message)
