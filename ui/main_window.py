"""Composition root Qt de CarvEx.

La fenêtre construit les composants et relie leurs signaux. Les workflows de
projet, Evidence et navigation sont délégués à des contrôleurs UI dédiés.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QProgressDialog,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from analysis.artifact_classifier import build_default_classifier
from bookmarks.repository import InMemoryBookmarkRepository
from bookmarks.service import BookmarkService
from carvex import generate_photorec_report
from core.duplicates import DuplicateIndex
from core.report_loader import LoadedReport, ReportLoader
from investigation.module import InvestigationProjectModule
from metadata.manager import build_default_manager
from metadata.module import MetadataProjectModule
from project.bookmarks_module import BookmarksProjectModule
from project.manager import ProjectManager
from project.modules import ProjectModuleRegistry
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.context import SelectionContext
from selection.file_selection import FileSelectionModel
from selection.manager import SelectionManager
from selection.resolver import FileSelectionRegistry, FileSelectionResolver
from timeline.service import build_default_service
from ui.application_navigation import ApplicationNavigationController, EvidenceWorkflowController
from ui.artifact_preloader import ArtifactPreloader
from ui.bookmarks_view import BookmarksView
from ui.details_panel import DetailsPanel
from ui.file_table import FileTable
from ui.investigation_view import InvestigationPanel
from ui.project_dialogs import NewProjectDialog
from ui.project_home import ProjectHome
from ui.project_session_controller import ProjectSessionController
from ui.project_workflow_controller import ProjectWorkflowController
from ui.timeline_view import TimelineView
from ui.workspace_controller import WorkspaceController


class MainWindow(QMainWindow):
    """Assemble les vues et les contrôleurs UI sans porter de logique métier."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CarvEx — Forensic File Analysis")
        self.resize(1280, 780)
        self.setMinimumSize(900, 560)

        self._metadata_manager = build_default_manager()
        self._artifact_classifier = build_default_classifier()
        self._artifact_preloader = ArtifactPreloader(self._metadata_manager, self._artifact_classifier, self)
        self._timeline_service = build_default_service(self._metadata_manager)
        self._project_modules = ProjectModuleRegistry()
        self._project_modules.register(MetadataProjectModule(self._metadata_manager))
        self._project_modules.register(BookmarksProjectModule())
        self._project_modules.register(InvestigationProjectModule())
        self.project_manager = ProjectManager(self._project_modules, self)
        self.bookmark_service = BookmarkService(InMemoryBookmarkRepository(), parent=self)
        self._recent_settings = QSettings("CarvEx", "CarvEx")
        self.selection_manager = SelectionManager(parent=self)
        self.file_selection = FileSelectionModel(self)
        self._selection_registry = FileSelectionRegistry()
        self._entity_resolver = CanonicalEntityResolver(self._selection_registry)
        self._selection_resolver = FileSelectionResolver(self._selection_registry)
        self.duplicate_index = DuplicateIndex()

        self._create_actions()
        self._create_central_area()
        self._create_status_bar()
        self._compose_controllers()
        self._create_menu_bar()
        self._create_tool_bar()
        self.project_manager.dirty_changed.connect(lambda _dirty: self._refresh_project_ui())
        self.project_manager.project_closed.connect(self.file_selection.clear)
        self._show_home()
        self.statusBar().showMessage("Prêt — aucune analyse chargée")

    def _create_actions(self) -> None:
        self.quit_action = QAction("Quitter", self, triggered=self.close)
        self.quit_action.setShortcut("Ctrl+Q")
        self.new_project_action = QAction("Nouveau projet…", self)
        self.open_project_action = QAction("Ouvrir un projet…", self)
        self.import_photo_rec_action = QAction("Importer un dossier PhotoRec…", self)
        self.save_project_action = QAction("Enregistrer", self)
        self.save_as_project_action = QAction("Enregistrer sous…", self)
        self.close_project_action = QAction("Fermer le projet", self)
        self.focus_search_action = QAction("Rechercher", self, triggered=self._focus_search)
        self.focus_search_action.setShortcut("Ctrl+F")
        self.next_result_action = QAction(
            "Résultat suivant", self, triggered=lambda: self.file_table.find_next_result()
        )
        self.next_result_action.setShortcut("F3")
        self.previous_result_action = QAction(
            "Résultat précédent", self, triggered=lambda: self.file_table.find_next_result(True)
        )
        self.previous_result_action.setShortcut("Shift+F3")
        self.focus_filters_action = QAction(
            "Atteindre les filtres", self, triggered=lambda: self.file_table.focus_filters()
        )
        self.focus_filters_action.setShortcut("Ctrl+L")
        self.toggle_details_action = QAction(
            "Afficher/masquer le panneau de droite", self, triggered=self._toggle_details
        )
        self.toggle_details_action.setShortcut("Space")
        self.open_viewer_action = QAction(
            "Ouvrir la visionneuse avancée", self, triggered=lambda: self.details_panel.preview_panel.open_viewer()
        )
        self.open_viewer_action.setShortcut("Return")
        self.select_visible_action = QAction(
            "Sélectionner les fichiers visibles", self, triggered=lambda: self.file_table.select_all_visible()
        )
        self.select_visible_action.setShortcut("Ctrl+A")
        self.recent_projects_menu = None

    def _create_central_area(self) -> None:
        self.file_table = FileTable(
            self,
            artifact_cache=self._artifact_classifier,
            artifact_preloader=self._artifact_preloader,
            bookmark_service=self.bookmark_service,
            entity_resolver=self._entity_resolver,
            file_selection=self.file_selection,
            duplicate_index=self.duplicate_index,
        )
        self._artifact_preloader.cache_updated.connect(self.file_table.refresh_artifact_filter)
        self.details_panel = DetailsPanel(
            self._metadata_manager,
            self._artifact_classifier,
            self,
            timeline_manager=self._timeline_service.manager,
        )
        files_page = QWidget(self)
        files_layout = QVBoxLayout(files_page)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.addWidget(self.file_table)

        self.timeline_view = TimelineView(
            self._timeline_service,
            self.bookmark_service,
            self,
            entity_resolver=self._entity_resolver,
            file_selection=self.file_selection,
        )
        self._entity_resolver.set_timeline_event_lookup(self.timeline_view.event_for_id)
        self.bookmarks_view = BookmarksView(self.bookmark_service, self, self._entity_resolver)
        self.investigation_panel = InvestigationPanel(self)
        self.main_tabs = QTabWidget(self)
        self.main_tabs.addTab(files_page, "📁 Fichiers")
        self.main_tabs.addTab(self.timeline_view, "🕒 Timeline")
        self.main_tabs.addTab(self.bookmarks_view, "★ Bookmarks")
        self.main_tabs.addTab(self.investigation_panel, "🔎 Investigation")

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.addWidget(self.main_tabs)
        self.content_splitter.addWidget(self.details_panel)
        self.main_tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.details_panel.setMinimumWidth(360)
        self.content_splitter.setCollapsible(1, False)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([780, 460])
        self._workspace_controller = WorkspaceController(
            self.project_manager,
            self.content_splitter,
            self.main_tabs,
            self.file_table,
            self.timeline_view,
            self.bookmarks_view,
            self.investigation_panel,
            self.details_panel,
        )
        self.project_home = ProjectHome(self)
        self.application_stack = QStackedWidget(self)
        self.application_stack.addWidget(self.project_home)
        self.application_stack.addWidget(self.content_splitter)
        self.setCentralWidget(self.application_stack)

    def _compose_controllers(self) -> None:
        self._navigation = ApplicationNavigationController(
            self.selection_manager,
            self._entity_resolver,
            self._selection_registry,
            self.file_table,
            self.main_tabs,
            self._show_temporary_status,
            self,
        )
        self._evidence = EvidenceWorkflowController(
            self._entity_resolver,
            self.investigation_panel,
            self.timeline_view,
            self.bookmarks_view,
            self.main_tabs,
            self._show_temporary_status,
            self._project_data_changed,
            refresh_file_markers=self.file_table.refresh_investigation_markers,
            parent=self,
        )
        self._session = ProjectSessionController(
            self.project_manager,
            self.bookmark_service,
            self.investigation_panel,
            self.details_panel,
            self._entity_resolver,
            self._selection_registry,
            self.selection_manager,
            self.file_table,
            self._metadata_manager,
            self._timeline_service,
            self.timeline_view,
            self.bookmarks_view,
            self._artifact_preloader,
            self._workspace_controller,
            self.application_stack,
            self.content_splitter,
            self.project_home,
            recent_projects=lambda: self._projects.recent_projects(),
            refresh_ui=self._refresh_project_ui,
            report_status=self._set_report_status,
            show_status=self._show_temporary_status,
            project_home_status=lambda: None,
        )
        self._projects = ProjectWorkflowController(
            self,
            self.project_manager,
            self._recent_settings,
            attach_project=self._attach_project,
            clear_project_ui=self._clear_project_ui,
            load_report=lambda report, update_metadata: self.load_report(report, update_metadata),
            capture_workspace=self._workspace_controller.capture,
            refresh_ui=self._refresh_project_ui,
            show_status=self._show_temporary_status,
            dialog_factory=NewProjectDialog,
            report_loader=ReportLoader,
            report_generator=generate_photorec_report,
            progress_factory=QProgressDialog,
        )
        self._connect_signals()

    def _connect_signals(self) -> None:
        self.new_project_action.triggered.connect(lambda _checked=False: self._new_project())
        self.open_project_action.triggered.connect(self._open_project)
        self.import_photo_rec_action.triggered.connect(self._import_photo_rec)
        self.save_project_action.triggered.connect(self._save_project)
        self.save_as_project_action.triggered.connect(self._save_project_as)
        self.close_project_action.triggered.connect(self._close_project)
        self.project_home.new_requested.connect(lambda: self._new_project())
        self.project_home.open_requested.connect(self._open_project)
        self.project_home.import_requested.connect(self._import_photo_rec)
        self.project_home.recent_requested.connect(self._open_recent_project)
        self.main_tabs.currentChanged.connect(lambda index: self.timeline_view.load_events() if index == 1 else None)
        self.selection_manager.selection_changed.connect(self._navigation.handle_selection_navigation)
        self.timeline_view.event_selected.connect(self._navigation.publish_timeline_selection)
        self.timeline_view.event_activated.connect(self._navigation.open_timeline_event)
        self.bookmarks_view.bookmark_selected.connect(self._navigation.publish_bookmark_selection)
        self.investigation_panel.selection_requested.connect(self._navigation.publish_investigation_selection)
        self.investigation_panel.file_requested.connect(self._navigation.open_investigation_file_default)
        self.file_table.record_selected.connect(self._navigation.publish_file_selection)
        self.timeline_view.investigation_item_requested.connect(self._evidence.add_timeline_event)
        self.timeline_view.bulk_investigation_requested.connect(self._evidence.add_files_bulk)
        self.timeline_view.bulk_collection_requested.connect(self._evidence.add_files_to_collection_bulk)
        self.bookmarks_view.investigation_item_requested.connect(self._evidence.add_bookmark)
        self.file_table.investigation_item_requested.connect(self._evidence.add_file)
        self.file_table.bulk_investigation_requested.connect(self._evidence.add_files_bulk)
        self.file_table.bulk_collection_requested.connect(self._evidence.add_files_to_collection_bulk)
        self.file_table.set_investigation_file_lookup(self.investigation_panel.has_file_item)
        self.file_table.set_investigation_item_lookup(self._evidence.file_is_in_investigation)
        self.timeline_view.set_investigation_presence_lookup(self._evidence.timeline_event_is_in_investigation)
        self.bookmarks_view.set_investigation_presence_lookup(self._evidence.bookmark_is_in_investigation)
        self.investigation_panel.file_item_changed.connect(self.file_table.refresh_investigation_marker)
        self.details_panel.bind_selection(self.selection_manager, self._selection_resolver)
        self.file_table.status_message.connect(self._show_temporary_status)
        self.file_table.view_state_changed.connect(self._update_view_status)
        self.file_table.correlation_summary_changed.connect(self._update_correlation_status)
        self.file_selection.changed.connect(lambda _change: self._update_runtime_status())
        self.bookmark_service.bookmarks_batch_changed.connect(lambda _result: self._project_data_changed())

    def _create_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("Fichier")
        for action in (self.new_project_action, self.open_project_action, self.import_photo_rec_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_project_action)
        file_menu.addAction(self.save_as_project_action)
        file_menu.addSeparator()
        file_menu.addAction(self.close_project_action)
        file_menu.addSeparator()
        self.recent_projects_menu = file_menu.addMenu("Projets récents")
        self.recent_projects_menu.aboutToShow.connect(self._populate_recent_projects)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        view_menu = self.menuBar().addMenu("Affichage")
        for action in (
            self.focus_search_action,
            self.next_result_action,
            self.previous_result_action,
            self.focus_filters_action,
            self.toggle_details_action,
            self.open_viewer_action,
            self.select_visible_action,
        ):
            view_menu.addAction(action)

    def _create_tool_bar(self) -> None:
        toolbar = QToolBar("Actions principales", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        style = self.style()
        self.new_project_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        self.open_project_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.save_project_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        for action in (self.new_project_action, self.open_project_action, self.save_project_action):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.import_photo_rec_action)
        self.addToolBar(toolbar)

    # Façade de compatibilité des slots historiques : la logique réside dans les contrôleurs.
    def _new_project(self, photo_rec_directory: str | None = None) -> None:
        self._projects.new_project(photo_rec_directory)

    def _open_project(self) -> None:
        self._projects.open_project()

    def _open_recent_project(self, root: str) -> None:
        self._projects.open_recent_project(root)

    def _import_photo_rec(self) -> None:
        self._projects.import_photo_rec()

    def _import_report_directory(self, directory: str, update_metadata: bool = True, progress=None) -> None:
        self._projects.import_report_directory(directory, update_metadata, progress)

    def _import_photo_rec_directory(self, source_directory: str, project_root) -> None:
        self._projects.import_photo_rec_directory(source_directory, project_root)

    def _save_project(self) -> None:
        self._projects.save_project()

    def _save_project_as(self) -> None:
        self._projects.save_project_as()

    def _close_project(self) -> None:
        self._projects.close_project()

    def _prepare_project_change(self) -> bool:
        return self._projects.prepare_project_change()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._prepare_project_change():
            super().closeEvent(event)
        else:
            event.ignore()

    def _attach_project(self, project, root: str) -> None:
        self._session.attach(project, root)
        if root:
            self._projects.add_recent(root)

    def _clear_project_ui(self) -> None:
        self._session.clear()

    def _show_home(self) -> None:
        self._session.show_home()

    def _capture_workspace(self) -> None:
        self._workspace_controller.capture()

    def _restore_workspace(self) -> None:
        self._workspace_controller.restore()

    # Façades de compatibilité pour les intégrations Qt existantes.
    def _open_timeline_event(self, event) -> None:
        self._navigation.open_timeline_event(event)

    def _publish_timeline_selection(self, event, origin: str = "timeline_view") -> None:
        self._navigation.publish_timeline_selection(event, origin)

    def _publish_file_selection(self, file_record) -> None:
        self._navigation.publish_file_selection(file_record)

    def _publish_bookmark_selection(self, bookmark) -> None:
        self._navigation.publish_bookmark_selection(bookmark)

    def _publish_investigation_selection(self, context: SelectionContext) -> None:
        self._navigation.publish_investigation_selection(context)

    def _add_file_to_investigation(self, file_record) -> None:
        self._evidence.add_file(file_record)

    def _add_timeline_event_to_investigation(self, event) -> None:
        self._evidence.add_timeline_event(event)

    def _add_bookmark_to_investigation(self, bookmark) -> None:
        self._evidence.add_bookmark(bookmark)

    def _file_is_in_investigation(self, file_record) -> bool:
        return self._evidence.file_is_in_investigation(file_record)

    def _timeline_event_is_in_investigation(self, event) -> bool:
        return self._evidence.timeline_event_is_in_investigation(event)

    def _bookmark_is_in_investigation(self, bookmark) -> bool:
        return self._evidence.bookmark_is_in_investigation(bookmark)

    @staticmethod
    def _view_header(view):
        return WorkspaceController.view_header(view)

    @classmethod
    def _sort_state(cls, view) -> tuple[int, str]:
        return WorkspaceController.sort_state(view)

    @classmethod
    def _column_order(cls, view) -> tuple[int, ...]:
        return WorkspaceController.column_order(view)

    def load_report(self, report: LoadedReport, update_metadata: bool = True) -> None:
        self._session.load_report(report, update_metadata)

    def _populate_recent_projects(self) -> None:
        if self.recent_projects_menu is None:
            return
        self.recent_projects_menu.clear()
        for root in self._projects.recent_projects():
            self.recent_projects_menu.addAction(root, lambda _checked=False, path=root: self._open_recent_project(path))
        if not self.recent_projects_menu.actions():
            action = self.recent_projects_menu.addAction("Aucun projet récent")
            action.setEnabled(False)

    def _project_data_changed(self) -> None:
        if self.project_manager.active_project is not None:
            self.project_manager.notify_persistent_change()
        self._refresh_project_ui()

    def _refresh_project_ui(self) -> None:
        project = self.project_manager.active_project
        if project is None:
            for action in (self.save_project_action, self.save_as_project_action, self.close_project_action):
                action.setEnabled(False)
            self.setWindowTitle("CarvEx — Aucun projet")
            self.project_status.setText("Aucun projet") if hasattr(self, "project_status") else None
            return
        dirty = " *" if self.project_manager.is_dirty else ""
        for action in (self.save_project_action, self.save_as_project_action, self.close_project_action):
            action.setEnabled(True)
        self.setWindowTitle(f"CarvEx — {project.metadata.name}.carvex{dirty}")
        if hasattr(self, "project_status"):
            state = "Modifications non enregistrées" if self.project_manager.is_dirty else "Projet enregistré"
            self.project_status.setText(f"{project.metadata.name} — {state}")
            self.bookmarks_status.setText(f"{self.bookmark_service.count()} bookmarks")
            self.modules_status.setText(f"{len(project.manifest.enabled_modules)} modules actifs")

    def _create_status_bar(self) -> None:
        self.project_status = QLabel("Projet non chargé", self)
        self.files_status = QLabel("0 fichiers", self)
        self.category_status = QLabel("Tous", self)
        self.results_status = QLabel("Affichage : 0 résultats", self)
        self.bookmarks_status = QLabel("0 bookmarks", self)
        self.modules_status = QLabel("0 module actif", self)
        self.correlations_status = QLabel("0 fichier corrélé", self)
        self.runtime_status = QLabel("0 sélectionné — 0 s", self)
        for widget in (
            self.project_status,
            self.files_status,
            self.category_status,
            self.results_status,
            self.bookmarks_status,
            self.modules_status,
            self.correlations_status,
            self.runtime_status,
        ):
            widget.setContentsMargins(8, 0, 8, 0)
            self.statusBar().addPermanentWidget(widget)

    def _set_report_status(self, count: int, visible: int) -> None:
        self.files_status.setText(f"{count} fichier" if count == 1 else f"{count} fichiers")
        self._update_view_status("Tous", visible)

    def _show_temporary_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _update_view_status(self, category: str, results: int) -> None:
        self.category_status.setText(category if category == "Tous" else f"{category} : {results}")
        self.results_status.setText(
            f"Affichage : {results} résultat" if results == 1 else f"Affichage : {results} résultats"
        )

    def _update_correlation_status(self, summary: dict[str, int]) -> None:
        self.correlations_status.setText(
            f"{summary['files']} fichiers corrélés — {summary['anomalies']} anomalies — "
            f"{summary['gps']} groupes GPS — {summary['devices']} groupes appareil"
        )

    def _focus_search(self) -> None:
        self.main_tabs.setCurrentIndex(0)
        self.file_table.search_field.setFocus()

    def _toggle_details(self) -> None:
        self.details_panel.setVisible(not self.details_panel.isVisible())

    def _update_runtime_status(self) -> None:
        self.runtime_status.setText(f"{self.file_selection.count} sélectionné(s)")
