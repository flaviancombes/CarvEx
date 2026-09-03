"""Projection Qt du projet actif, sans logique dans ``MainWindow``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from PySide6.QtCore import QTimer

from bookmarks.repository import InMemoryBookmarkRepository
from core.file_identity import assert_project_identity_compatible
from core.report_loader import LoadedReport
from investigation.physical_representation import InvestigationPhysicalRepresentationService
from investigation.service import InvestigationService
from metadata.commit import MetadataCommitService
from metadata.correlation import MetadataCorrelationEngine, MetadataCorrelationStore
from metadata.indexing import MetadataIndexingService
from project.models import ProjectMetadata, ReportSourceAuditEntry
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.manager import SelectionManager
from selection.resolver import FileSelectionRegistry
from ui.investigation_details_provider import InvestigationDetailsProvider
from ui.ui_responsiveness_instrumentation import mark_pipeline_finished, stop_ui_responsiveness_probe
from utils import performance
from utils.performance import (
    IndexingCompletionReport,
    finish_pipeline_profile,
    log_cache_sizes,
    measure,
    pipeline_stage,
    start_pipeline_profile,
)


class ProjectSessionController:
    """Raccorde ou détache un projet des services et vues déjà construits."""

    def __init__(
        self,
        project_manager,
        bookmark_service,
        investigation_panel,
        details_panel,
        entity_resolver: CanonicalEntityResolver,
        selection_registry: FileSelectionRegistry,
        selection_manager: SelectionManager,
        file_table,
        metadata_manager,
        timeline_service,
        timeline_view,
        bookmarks_view,
        artifact_preloader,
        background_tasks,
        workspace_controller,
        application_stack,
        content_widget,
        home_widget,
        *,
        recent_projects: Callable[[], list[str]],
        refresh_ui: Callable[[], None],
        report_status: Callable[[int, int], None],
        show_status: Callable[[str], None],
        project_home_status: Callable[[], None],
    ) -> None:
        self._project_manager = project_manager
        self._bookmark_service = bookmark_service
        self._investigation_panel = investigation_panel
        self._details_panel = details_panel
        self._entity_resolver = entity_resolver
        self._selection_registry = selection_registry
        self._selection_manager = selection_manager
        self._file_table = file_table
        self._metadata_manager = metadata_manager
        self._timeline_service = timeline_service
        self._timeline_view = timeline_view
        self._bookmarks_view = bookmarks_view
        self._artifact_preloader = artifact_preloader
        self._background_tasks = background_tasks
        self._workspace_controller = workspace_controller
        self._application_stack = application_stack
        self._content_widget = content_widget
        self._home_widget = home_widget
        self._recent_projects = recent_projects
        self._refresh_ui = refresh_ui
        self._report_status = report_status
        self._show_status = show_status
        self._project_home_status = project_home_status
        self._details_provider: InvestigationDetailsProvider | None = None
        self._physical_representation: InvestigationPhysicalRepresentationService | None = None
        self._metadata_indexing: MetadataIndexingService | None = None
        self._metadata_commit: MetadataCommitService | None = None
        self._metadata_store = None
        self._correlation_engine: MetadataCorrelationEngine | None = None
        self._correlation_store: MetadataCorrelationStore | None = None
        self._metadata_correlations_dirty = False
        self._metadata_timer = QTimer(project_manager)
        self._metadata_timer.setInterval(25)
        self._metadata_timer.timeout.connect(self._drain_metadata_indexing)
        self._project_manager.project_closing.connect(self._stop_metadata_indexing)

    def attach(self, project, root: str) -> None:
        bookmarks = project.repository.module_repository("bookmarks", "bookmarks")
        self._bookmark_service.attach_repository(bookmarks)
        self._attach_metadata_indexing(project)
        self._attach_investigation(project)
        self.reset_views()
        self._workspace_controller.restore()
        self._application_stack.setCurrentWidget(self._content_widget)
        self._refresh_ui()

    def clear(self) -> None:
        stop_ui_responsiveness_probe()
        with measure("shutdown.session_stop_metadata"), performance.operation("Shutdown", "session_stop_metadata"):
            self._stop_metadata_indexing()
        with measure("shutdown.session_detach_views"), performance.operation("Shutdown", "session_detach_views"):
            self._artifact_preloader.clear_cache()
            self._bookmark_service.attach_repository(InMemoryBookmarkRepository())
            self._file_table.set_metadata_index(None)
            self._file_table.set_correlation_index(None)
            self._details_panel.set_correlation_index(None)
            self._investigation_panel.detach()
        self._physical_representation = None
        self._background_tasks.finish_all(cancelled=True)
        self._entity_resolver.set_investigation_item_lookup(None)
        if self._details_provider is not None:
            self._details_panel.unregister_provider(self._details_provider)
            self._details_provider = None
        with measure("shutdown.session_reset_views"), performance.operation("Shutdown", "session_reset_views"):
            self.reset_views()
        self.show_home()

    def reset_views(self) -> None:
        self._file_table.set_files(())
        self._artifact_preloader.clear_cache()
        self._selection_registry.set_records(())
        self._timeline_service.set_records(())
        self._timeline_view.reset_events()
        self._selection_manager.clear_history()
        self._details_panel.set_file(None)
        self._report_status(0, 0)

    def show_home(self) -> None:
        self._home_widget.set_recents(self._recent_projects())
        self._application_stack.setCurrentWidget(self._home_widget)
        self._project_home_status()
        self._refresh_ui()

    def load_report(self, report: LoadedReport, update_metadata: bool = True) -> None:
        if self._project_manager.active_project is None:
            project = self._project_manager.create_project(ProjectMetadata("Investigation CarvEx"))
            self.attach(project, "")
        project = self._project_manager.active_project
        metadata = project.metadata
        assert_project_identity_compatible(metadata.file_identity_scheme, metadata.file_identity_namespace)
        source_reference = str(report.report_path) if update_metadata else metadata.source_reference
        if (
            source_reference != metadata.source_reference
            or metadata.file_identity_scheme != report.file_identity_scheme
            or metadata.source_snapshot != report.source_snapshot
        ):
            source_audit = metadata.source_audit
            if update_metadata:
                source_audit = (*source_audit, self._source_audit_entry(metadata, source_reference, report))
            self._project_manager.update_metadata(
                replace(
                    metadata,
                    source_reference=source_reference,
                    file_identity_namespace=None,
                    file_identity_scheme=report.file_identity_scheme,
                    source_snapshot=report.source_snapshot,
                    source_audit=source_audit,
                )
            )
        with pipeline_stage("FileTable.set_files"):
            self._file_table.set_files(report.files)
        if self._physical_representation is not None:
            with pipeline_stage("InvestigationPhysicalRepresentation.set_file_records"):
                self._physical_representation.set_file_records(report.files)
        with pipeline_stage("FileSelectionRegistry.set_records"):
            self._selection_registry.set_records(report.files)
        with pipeline_stage("BookmarksView.refresh_file_projection"):
            self._bookmarks_view.refresh_file_projection()
        self._selection_manager.clear_history()
        with pipeline_stage("TimelineService.set_records"):
            self._timeline_service.set_records(report.files)
        with pipeline_stage("TimelineView.reset_events"):
            self._timeline_view.reset_events()
        self._details_panel.set_file(None)
        count = self._file_table.file_count
        self._report_status(count, self._file_table.visible_file_count)
        log_cache_sizes(self._metadata_manager, self._timeline_service)
        with pipeline_stage("MainWindow.refresh_ui"):
            self._refresh_ui()
        self._show_status("Prêt")
        with pipeline_stage("MetadataIndexingService.start"):
            self._start_metadata_indexing(report.files)

    def _attach_metadata_indexing(self, project) -> None:
        store = project.repository.module_repository("metadata", "store")
        indexing = project.repository.module_repository("metadata", "indexing_service")
        assert isinstance(indexing, MetadataIndexingService)
        self._metadata_store = store
        self._file_table.set_metadata_index(store.index)
        correlation_store = project.repository.module_repository("metadata", "correlation_store")
        correlation_engine = project.repository.module_repository("metadata", "correlation_engine")
        self._file_table.set_correlation_index(correlation_store.index)
        self._details_panel.set_correlation_index(correlation_store.index, self._file_table.file_label_for)
        self._metadata_indexing = indexing
        self._metadata_commit = MetadataCommitService(store, indexing, project.repository.flush)
        self._correlation_store = correlation_store
        self._correlation_engine = correlation_engine

    def _start_metadata_indexing(self, records) -> None:
        if self._metadata_indexing is None:
            return
        self._metadata_manager.set_store_writable(False)
        try:
            self._metadata_indexing.start(records, self._metadata_manager)
        except Exception:
            self._metadata_manager.set_store_writable(True)
            raise
        if self._metadata_indexing.is_running:
            progress = self._metadata_indexing.progress
            self._background_tasks.start_task(
                "metadata",
                "Indexation des métadonnées",
                total=progress.total,
                current=progress.indexed + progress.failed,
            )
            self._metadata_timer.start()
            self._show_metadata_progress()
        else:
            self._metadata_manager.set_store_writable(True)

    def _drain_metadata_indexing(self) -> None:
        indexing = self._metadata_indexing
        commit = self._metadata_commit
        if indexing is None or commit is None:
            self._metadata_timer.stop()
            return
        try:
            report = IndexingCompletionReport()
            with (
                report.stage("Attente des derniers workers / file de commits"),
                performance.operation("MetadataIndexing", "collect_completed"),
                pipeline_stage("MetadataIndexingService.collect_completed"),
            ):
                completed = indexing.collect_completed()
            committed = False
            with report.stage("MetadataCommitService (derniers lots)"):
                for result in completed:
                    with (
                        performance.operation("MetadataIndexing", "commit_batch"),
                        pipeline_stage("MetadataCommitService.commit"),
                    ):
                        commit.commit(result)
                    committed = True
            if committed:
                self._metadata_correlations_dirty = True
                with report.stage("Rafraîchissement FileTable"):
                    self._file_table.refresh_metadata_filters()
            with (
                report.stage("Planification finale des workers"),
                pipeline_stage("MetadataIndexingService.schedule_workers"),
            ):
                indexing.schedule_workers()
        except Exception as error:
            indexing.cancel()
            self._show_status(f"Indexation des métadonnées interrompue : {error}")
        self._show_metadata_progress()
        if not indexing.is_running and not indexing.has_completed:
            self._metadata_timer.stop()
            self._metadata_manager.set_store_writable(True)
            self._background_tasks.set_phase("metadata", "Finalisation de l’indexation des métadonnées…")
            try:
                self._finalize_metadata_indexing(report)
            finally:
                self._background_tasks.finish_task("metadata")

    def _stop_metadata_indexing(self, *_args) -> None:
        self._metadata_timer.stop()
        indexing = self._metadata_indexing
        commit = self._metadata_commit
        if indexing is None:
            return
        progress = indexing.progress
        if performance.ENABLED:
            performance.LOGGER.info(
                "[Shutdown] metadata workers active_records=%d completed=%s",
                progress.indexing,
                indexing.has_completed,
            )
        with measure("shutdown.metadata_workers_stop"), performance.operation("Shutdown", "metadata_workers_stop"):
            indexing.shutdown()
        if commit is not None:
            with (
                measure("shutdown.metadata_collect_completed"),
                performance.operation("Shutdown", "metadata_collect_completed"),
            ):
                completed = indexing.collect_completed()
            if completed:
                with (
                    measure("shutdown.metadata_commit_completed"),
                    performance.operation("Shutdown", "metadata_commit_completed"),
                ):
                    for result in completed:
                        commit.commit(result)
                self._metadata_correlations_dirty = True
            if self._metadata_correlations_dirty:
                self._finalize_metadata_indexing(for_shutdown=bool(_args))
        self._metadata_manager.set_store_writable(True)
        self._metadata_indexing = None
        self._metadata_commit = None
        self._metadata_store = None
        self._correlation_engine = None
        self._correlation_store = None
        self._metadata_correlations_dirty = False
        self._background_tasks.finish_task("metadata", cancelled=True)

    def _finalize_metadata_indexing(
        self,
        report: IndexingCompletionReport | None = None,
        *,
        for_shutdown: bool = False,
    ) -> None:
        """Build derived correlations once, then persist the coherent checkpoint."""
        commit = self._metadata_commit
        if commit is None:
            return
        report = report or IndexingCompletionReport()
        start_pipeline_profile("Pipeline metadata après progression 100 %")
        if self._metadata_correlations_dirty:
            engine = self._correlation_engine
            store = self._correlation_store
            if engine is not None and store is not None:
                with (
                    report.stage("Génération des corrélations"),
                    performance.operation("MetadataCorrelation", "build_and_store"),
                    pipeline_stage("MetadataCorrelationEngine.build_and_store"),
                ):
                    engine.build_and_store(store)
                if not for_shutdown:
                    with report.stage("Rafraîchissement FileTable (corrélations)"):
                        self._file_table.set_correlation_index(store.index)
                    with report.stage("Rafraîchissement DetailsPanel (corrélations)"):
                        self._details_panel.set_correlation_index(store.index, self._file_table.file_label_for)
            self._metadata_correlations_dirty = False
        with (
            performance.operation("MetadataIndexing", "flush_pending"),
            pipeline_stage("MetadataCommitService.flush_pending"),
        ):
            commit.flush_pending(report.record_elapsed)
        mark_pipeline_finished()
        finish_pipeline_profile()
        if performance.ENABLED:
            QTimer.singleShot(0, report.finish)

    def _show_metadata_progress(self) -> None:
        if self._metadata_indexing is None:
            return
        progress = self._metadata_indexing.progress
        self._background_tasks.update_task(
            "metadata",
            current=progress.indexed + progress.failed,
            total=progress.total,
            label="Indexation des métadonnées",
        )
        if progress.percentage >= 100:
            start_pipeline_profile("Pipeline metadata après progression 100 %")
        self._show_status(
            f"Indexation des métadonnées : {progress.percentage:.0f} % "
            f"({progress.indexed + progress.failed}/{progress.total})"
        )

    @staticmethod
    def _source_audit_entry(metadata, source_reference: str | None, report: LoadedReport) -> ReportSourceAuditEntry:
        previous = metadata.source_snapshot
        if previous is None:
            action = "source_attached"
            summary = "Rapport source rattaché au projet."
        elif previous.matches_evidence_inventory(report.source_snapshot):
            action = (
                "source_relocated" if metadata.source_reference != source_reference else "report_representation_changed"
            )
            summary = (
                "Rapport source relocalisé : inventaire des preuves inchangé."
                if action == "source_relocated"
                else "Présentation du rapport modifiée : inventaire des preuves inchangé."
            )
        else:
            action = "source_replaced"
            summary = "Rapport source remplacé : inventaire des preuves modifié."
        return ReportSourceAuditEntry(
            occurred_at=datetime.now(UTC),
            action=action,
            previous_reference=metadata.source_reference,
            current_reference=source_reference,
            previous_fingerprint_sha256=None if previous is None else previous.fingerprint_sha256,
            current_fingerprint_sha256=report.source_snapshot.fingerprint_sha256,
            previous_evidence_fingerprint_sha256=None if previous is None else previous.evidence_fingerprint_sha256,
            current_evidence_fingerprint_sha256=report.source_snapshot.evidence_fingerprint_sha256,
            summary=summary,
        )

    def _attach_investigation(self, project) -> None:
        service = project.repository.module_repository("investigation", "service")
        queries = project.repository.module_repository("investigation", "query_service")
        validator = project.repository.module_repository("investigation", "integrity_validator")
        representation = project.repository.module_repository("investigation", "physical_representation")
        assert isinstance(service, InvestigationService)
        assert isinstance(representation, InvestigationPhysicalRepresentationService)
        self._physical_representation = representation
        self._entity_resolver.set_investigation_item_lookup(service.get_item)
        self._investigation_panel.attach(service, queries, validator, self._selection_manager, self._entity_resolver)
        if self._details_provider is not None:
            self._details_panel.unregister_provider(self._details_provider)
        self._details_provider = InvestigationDetailsProvider(service, queries, self._entity_resolver)
        self._details_panel.register_provider(self._details_provider)
