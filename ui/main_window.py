"""Fenêtre principale de l'application desktop CarvEx."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QStyle, QToolBar

from core.report_loader import LoadedReport
from ui.details_panel import DetailsPanel
from ui.file_table import FileTable


class MainWindow(QMainWindow):
    """Shell d'interface qui présente un rapport déjà généré par CarvEx."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CarvEx — Forensic File Analysis")
        self.resize(1280, 780)
        self.setMinimumSize(900, 560)

        self._create_actions()
        self._create_menu_bar()
        self._create_tool_bar()
        self._create_central_area()
        self._create_status_bar()
        self.statusBar().showMessage("Prêt — aucune analyse chargée")

    def _create_actions(self) -> None:
        self.open_case_action = QAction("Ouvrir le projet", self)
        self.open_case_action.setEnabled(False)
        self.open_case_action.setStatusTip("Le chargement se fait au démarrage dans cette étape")

        self.refresh_action = QAction("Actualiser", self)
        self.refresh_action.setEnabled(False)
        self.refresh_action.setStatusTip("Actualisation prévue dans une prochaine étape")

        self.settings_action = QAction("Paramètres", self)
        self.settings_action.setEnabled(False)
        self.settings_action.setStatusTip("Paramètres prévus dans une prochaine étape")

        self.quit_action = QAction("Quitter", self)
        self.quit_action.setShortcut("Ctrl+Q")
        self.quit_action.triggered.connect(self.close)

    def _create_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("Fichier")
        file_menu.addAction(self.open_case_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

    def _create_tool_bar(self) -> None:
        toolbar = QToolBar("Actions principales", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        style = self.style()
        self.open_case_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.refresh_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.settings_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        toolbar.addAction(self.open_case_action)
        toolbar.addAction(self.refresh_action)
        toolbar.addSeparator()
        toolbar.addAction(self.settings_action)
        self.addToolBar(toolbar)

    def _create_central_area(self) -> None:
        self.file_table = FileTable(self)
        self.details_panel = DetailsPanel(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.file_table)
        splitter.addWidget(self.details_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([880, 360])
        self.setCentralWidget(splitter)
        self.file_table.record_selected.connect(self.details_panel.set_file)
        self.file_table.status_message.connect(self._show_temporary_status)
        self.file_table.view_state_changed.connect(self._update_view_status)

    def _create_status_bar(self) -> None:
        self.project_status = QLabel("Projet non chargé", self)
        self.files_status = QLabel("0 fichiers", self)
        self.category_status = QLabel("Tous", self)
        self.results_status = QLabel("Affichage : 0 résultats", self)
        for widget in (self.project_status, self.files_status, self.category_status, self.results_status):
            widget.setContentsMargins(8, 0, 8, 0)
            self.statusBar().addPermanentWidget(widget)

    def load_report(self, report: LoadedReport) -> None:
        """Connecte les données backend existantes à la vue Qt."""
        self.file_table.set_files(report.files)
        self.details_panel.set_file(None)
        count = self.file_table.file_count
        self.project_status.setText("Projet chargé")
        self.files_status.setText(f"{count} fichier" if count == 1 else f"{count} fichiers")
        self._update_view_status("Tous", self.file_table.visible_file_count)
        self.statusBar().showMessage("Prêt")

    def _show_temporary_status(self, message: str) -> None:
        """Affiche les retours d'action sans contenir leur logique métier."""
        self.statusBar().showMessage(message, 5000)

    def _update_view_status(self, category: str, results: int) -> None:
        """Met à jour les indicateurs visuels sans modifier les données affichées."""
        self.category_status.setText(category if category == "Tous" else f"{category} : {results}")
        self.results_status.setText(f"Affichage : {results} résultat" if results == 1 else f"Affichage : {results} résultats")
