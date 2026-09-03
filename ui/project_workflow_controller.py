"""Workflow UI des projets CarvEx.

Le contrôleur concentre les dialogues et la coordination des composants de
projet. Il délègue tout état durable à ``ProjectManager`` et toute projection
de rapport à la fenêtre qui assemble les vues.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Slot
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog

from carvex import generate_photorec_report
from core.file_identity import LegacyFileIdentityError
from core.import_progress import ImportProgress
from core.report_loader import LoadedReport, ReportLoader, ReportLoadError
from project.locking import ProjectLockedError
from project.manager import ProjectManager
from project.models import ProjectMetadata, ReportSourceSnapshot
from project.storage import JsonProjectStorage
from ui.photo_rec_import_worker import PhotoRecImportWorker
from ui.project_dialogs import NewProjectDialog
from ui.ui_responsiveness_instrumentation import mark_pipeline_finished, start_ui_responsiveness_probe
from utils import performance
from utils.performance import finish_pipeline_profile, measure, operation, pipeline_stage, start_pipeline_profile


class ProjectWorkflowController(QObject):
    """Exécute les actions Projet sans connaître les widgets métier de CarvEx."""

    def __init__(
        self,
        parent,
        project_manager: ProjectManager,
        settings,
        *,
        attach_project: Callable[[Any, str], None],
        clear_project_ui: Callable[[], None],
        load_report: Callable[[LoadedReport, bool], None],
        capture_workspace: Callable[[], None],
        refresh_ui: Callable[[], None],
        show_status: Callable[[str], None],
        dialog_factory=NewProjectDialog,
        report_loader=ReportLoader,
        report_generator=generate_photorec_report,
        progress_factory=QProgressDialog,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._project_manager = project_manager
        self._settings = settings
        self._attach_project = attach_project
        self._clear_project_ui = clear_project_ui
        self._load_report = load_report
        self._capture_workspace = capture_workspace
        self._refresh_ui = refresh_ui
        self._show_status = show_status
        self._dialog_factory = dialog_factory
        self._report_loader = report_loader
        self._report_generator = report_generator
        self._progress_factory = progress_factory
        self._import_thread: QThread | None = None
        self._import_worker: PhotoRecImportWorker | None = None
        self._import_progress: QProgressDialog | None = None

    def new_project(self, photo_rec_directory: str | None = None) -> None:
        dialog = self._dialog_factory(photo_rec_directory, self._parent)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        if not dialog.name_field.text().strip() or not dialog.location_field.text().strip():
            QMessageBox.warning(self._parent, "Projet incomplet", "Le nom et l'emplacement du projet sont requis.")
            return
        root = dialog.project_root
        if JsonProjectStorage.exists(root):
            QMessageBox.warning(self._parent, "Projet existant", "Un projet existe déjà à cet emplacement.")
            return
        if not self.prepare_project_change():
            return
        try:
            project = self._project_manager.create_project(
                ProjectMetadata(
                    dialog.name_field.text().strip(), description=dialog.description_field.toPlainText().strip() or None
                ),
                JsonProjectStorage(root, create=True),
            )
        except ProjectLockedError as error:
            QMessageBox.warning(self._parent, "Projet verrouillé", str(error))
            return
        self._attach_project(project, str(root))
        if dialog.import_field.text().strip():
            self.import_photo_rec_directory(dialog.import_field.text().strip(), root)

    def open_project(self) -> None:
        project_file, _selected_filter = QFileDialog.getOpenFileName(
            self._parent,
            "Ouvrir un projet CarvEx",
            filter="Projet CarvEx (project.carvex)",
        )
        if project_file:
            self.open_recent_project(project_file)

    def open_recent_project(self, root: str) -> None:
        if not JsonProjectStorage.exists(root):
            self.remove_recent(root)
            QMessageBox.warning(self._parent, "Projet introuvable", "Ce projet n'existe plus.")
            return
        if self._project_manager.active_project is not None and not self.prepare_project_change():
            return
        try:
            project = self._project_manager.open_project(root)
        except (OSError, ValueError, ProjectLockedError) as error:
            QMessageBox.warning(self._parent, "Ouverture impossible", str(error))
            return
        self._attach_project(project, root)
        self.load_saved_report_source(project)

    def import_photo_rec(self) -> None:
        directory = QFileDialog.getExistingDirectory(self._parent, "Importer un dossier PhotoRec")
        if directory:
            self.new_project(directory)

    def import_report_directory(
        self,
        directory: str,
        update_metadata: bool = True,
        progress: QProgressDialog | None = None,
    ) -> None:
        try:
            report = self._report_loader.load(directory)
        except ReportLoadError as error:
            if progress is not None:
                progress.close()
            QMessageBox.warning(self._parent, "Rapport CarvEx introuvable", str(error))
            return
        self._consume_loaded_report(report, update_metadata, progress)

    def _consume_loaded_report(
        self,
        report: LoadedReport,
        update_metadata: bool,
        progress: QProgressDialog | None = None,
    ) -> None:
        active_project = self._project_manager.active_project
        if active_project is not None and not self._accept_report_source(active_project, report, update_metadata):
            if progress is not None:
                progress.close()
            self._show_status("Rapport source non chargé : chaîne de conservation à confirmer.")
            return
        try:
            with operation("ProjectWorkflow", "load_report"), pipeline_stage("ProjectWorkflowController.load_report"):
                self._load_report(report, update_metadata)
        except LegacyFileIdentityError as error:
            if progress is not None:
                progress.close()
            QMessageBox.warning(self._parent, "Migration d'identité requise", str(error))
            self._show_status("Rapport source non chargé : identité historique non migrable.")
            return
        if progress is not None:
            mark_pipeline_finished()
            progress.close()
            finish_pipeline_profile()

    def import_photo_rec_directory(
        self,
        source_directory: str,
        project_root: Path,
    ) -> None:
        """Lance le pipeline PhotoRec hors UI, puis rattache le rapport produit dans le thread Qt."""
        if self._import_thread is not None:
            self._show_status("Un import PhotoRec est déjà en cours.")
            return
        progress = self._progress_factory("Préparation de l'import...", None, 0, 100, self._parent)
        progress.setWindowTitle("Import PhotoRec")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.show()
        self._import_progress = progress
        thread = QThread(self)
        worker = PhotoRecImportWorker(
            source_directory,
            project_root,
            None,
            self._report_generator,
            self._report_loader,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._update_import_progress, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(self._on_import_completed, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_import_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clear_import_worker)
        thread.finished.connect(thread.deleteLater)
        self._import_thread = thread
        self._import_worker = worker
        thread.start()

    @Slot(object)
    def _update_import_progress(self, update: ImportProgress) -> None:
        progress = self._import_progress
        if progress is None:
            return
        if update.percent is None:
            progress.setRange(0, 0)
        else:
            progress.setRange(0, 100)
            if update.percent >= 100:
                start_pipeline_profile("Pipeline import après progression 100 %")
                start_ui_responsiveness_probe(progress, self._parent)
            progress.setValue(update.percent)
        progress.setLabelText(update.detail)

    @Slot(object)
    def _on_import_completed(self, report: LoadedReport) -> None:
        self._consume_loaded_report(report, True, self._import_progress)

    @Slot(str)
    def _on_import_failed(self, message: str) -> None:
        if self._import_progress is not None:
            self._import_progress.close()
        QMessageBox.warning(self._parent, "Import PhotoRec impossible", message)

    @Slot()
    def _clear_import_worker(self) -> None:
        self._import_thread = None
        self._import_worker = None
        self._import_progress = None

    def save_project(self) -> None:
        if self._project_manager.active_project is None:
            return
        with operation("ProjectWorkflow", "save_project"):
            self._capture_workspace()
            self._project_manager.save_project()
            self._refresh_ui()

    def save_project_as(self) -> None:
        if self._project_manager.active_project is None:
            return
        directory = QFileDialog.getExistingDirectory(self._parent, "Enregistrer le projet sous")
        if not directory:
            return
        selected = Path(directory)
        name = self._project_manager.active_project.metadata.name
        root = selected if selected.suffix.lower() == ".carvex" else selected / f"{name}.carvex"
        if JsonProjectStorage.exists(root):
            QMessageBox.warning(self._parent, "Projet existant", "Un projet existe déjà à cet emplacement.")
            return
        project = self._project_manager.save_as(JsonProjectStorage(root, create=True))
        self._attach_project(project, str(root))

    def close_project(self) -> None:
        if self.prepare_project_change():
            self._clear_project_ui()

    def prepare_project_change(self) -> bool:
        with measure("shutdown.total"), operation("Shutdown", "total"):
            return self._prepare_project_change()

    def _prepare_project_change(self) -> bool:
        project = self._project_manager.active_project
        if project is None:
            if performance.ENABLED:
                performance.LOGGER.info("[Shutdown] close requested active_project=false")
            return True
        if performance.ENABLED:
            performance.LOGGER.info(
                "[Shutdown] close requested active_project=true dirty=%s",
                self._project_manager.is_dirty,
            )
        with measure("shutdown.capture_workspace"), operation("Shutdown", "capture_workspace"):
            self._capture_workspace()
        if performance.ENABLED:
            self._project_manager.log_dirty_state("after_capture_workspace")
        if self._project_manager.is_dirty:
            answer = QMessageBox.question(
                self._parent,
                "Modifications non enregistrées",
                "Le projet contient des modifications non enregistrées. Enregistrer avant de continuer ?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save:
                # ``close_project(save=True)`` prépare et persiste déjà toutes
                # les données. Appeler ``save_project`` juste avant sérialisait
                # le projet complet une deuxième fois sans rendre les données
                # plus sûres.
                with (
                    measure("shutdown.project_close_after_save_choice"),
                    operation("Shutdown", "project_close_after_save_choice"),
                ):
                    self._project_manager.close_project(save=True)
            else:
                with measure("shutdown.project_close_discard"), operation("Shutdown", "project_close_discard"):
                    self._project_manager.close_project(save=False)
        else:
            with measure("shutdown.project_close_clean"), operation("Shutdown", "project_close_clean"):
                self._project_manager.close_project(save=True)
        return True

    def load_saved_report_source(self, project) -> None:
        source = project.metadata.source_reference
        if not source:
            return
        report_path = Path(source)
        if not report_path.is_file():
            self.handle_missing_report_source(str(report_path))
            return
        try:
            report = self._report_loader.load(report_path.parent)
        except ReportLoadError as error:
            QMessageBox.warning(
                self._parent,
                "Rapport source illisible",
                f"Le rapport associé au projet ne peut pas être chargé :\n{error}\n\n"
                "Le projet reste ouvert, mais aucun fichier source n'est affiché.",
            )
            return
        snapshot = project.metadata.source_snapshot
        if snapshot is None:
            QMessageBox.information(
                self._parent,
                "Rapport source non vérifié",
                "Ce projet a été créé avant l'enregistrement des empreintes de rapport. "
                "L'empreinte du rapport actuellement sélectionné va être enregistrée.",
            )
        elif not self._accept_report_source(project, report, False):
            self._show_status("Rapport source non chargé : empreinte différente.")
            return
        try:
            self._load_report(report, False)
        except LegacyFileIdentityError as error:
            QMessageBox.warning(self._parent, "Migration d'identité requise", str(error))
            self._show_status("Rapport source non chargé : identité historique non migrable.")

    def _accept_report_source(self, project, report: LoadedReport, update_metadata: bool) -> bool:
        expected = project.metadata.source_snapshot
        if expected is None:
            return True
        source_changed = update_metadata and not self._same_path(
            project.metadata.source_reference, str(report.report_path)
        )
        if not expected.matches_evidence_inventory(report.source_snapshot):
            return self.confirm_changed_report_source(expected, report.source_snapshot, True)
        if source_changed:
            return self.confirm_changed_report_source(expected, report.source_snapshot, False)
        if not expected.matches_content(report.source_snapshot):
            self._show_status("Rapport réordonné ou enrichi visuellement : inventaire des preuves inchangé.")
        return True

    @staticmethod
    def _same_path(first: str | None, second: str) -> bool:
        if first is None:
            return False
        return Path(first).resolve(strict=False) == Path(second).resolve(strict=False)

    def confirm_changed_report_source(
        self,
        expected: ReportSourceSnapshot,
        actual: ReportSourceSnapshot,
        inventory_changed: bool = True,
    ) -> bool:
        reason = (
            "L'inventaire canonique des preuves diffère du rapport enregistré."
            if inventory_changed
            else "Le rapport provient d'un nouvel emplacement, bien que son inventaire de preuves soit identique."
        )
        answer = QMessageBox.warning(
            self._parent,
            "Chaîne de conservation : rapport à confirmer",
            f"{reason}\n\n"
            f"Enregistré : {self.snapshot_description(expected)}\n"
            f"Actuel : {self.snapshot_description(actual)}\n\n"
            "Charger ce rapport mettra à jour la référence et laissera une trace d'audit. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def handle_missing_report_source(self, report_path: str) -> None:
        dialog = QMessageBox(self._parent)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Rapport source introuvable")
        dialog.setText("Le rapport PhotoRec associé au projet est introuvable.")
        dialog.setInformativeText(
            f"Référence enregistrée :\n{report_path}\n\n"
            "Le rapport a été déplacé ou supprimé. Vous pouvez le localiser ou ouvrir le projet sans rapport source."
        )
        locate = dialog.addButton("Localiser le rapport…", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Ouvrir sans rapport", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is locate:
            directory = QFileDialog.getExistingDirectory(self._parent, "Localiser le dossier du rapport PhotoRec")
            if directory:
                self.import_report_directory(directory, update_metadata=True)
        else:
            self._show_status("Projet ouvert sans rapport source : référence introuvable.")

    def recent_projects(self) -> list[str]:
        values = self._settings.value("recent_projects", [])
        raw_paths = values if isinstance(values, (list, tuple)) else ([values] if values else [])
        paths = [str(value) for value in raw_paths]
        existing = [path for path in paths if JsonProjectStorage.exists(path)]
        if existing != paths:
            self._settings.setValue("recent_projects", existing)
        return existing

    def add_recent(self, root: str) -> None:
        paths = [path for path in self.recent_projects() if path != root]
        self._settings.setValue("recent_projects", [root, *paths][:10])

    def remove_recent(self, root: str) -> None:
        self._settings.setValue("recent_projects", [path for path in self.recent_projects() if path != root])

    @staticmethod
    def snapshot_description(snapshot: ReportSourceSnapshot) -> str:
        version = snapshot.report_version or "non déclarée"
        return (
            f"SHA-256 {snapshot.fingerprint_sha256[:12]}… — "
            f"{snapshot.file_count} fichiers — version {version} — "
            f"{snapshot.modified_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}"
        )
