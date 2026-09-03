"""Cycle de vie du projet actif, sans connaissance des modules concrets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from project.codecs import create_core_codec_registry
from project.migrations import ProjectMigrationService
from project.models import (
    CURRENT_SCHEMA_VERSION,
    Project,
    ProjectManifest,
    ProjectMetadata,
    ProjectSettings,
    ProjectState,
)
from project.modules import ProjectModuleContext, ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage, JsonProjectStorage, ProjectStorageAdapter
from project.workspaces import WorkspaceManager
from utils.performance import ENABLED, LOGGER, measure, operation


class ProjectManager(QObject):
    project_opened = Signal(object)
    project_closing = Signal(object)
    project_closed = Signal()
    project_changed = Signal(object)
    dirty_changed = Signal(bool)

    def __init__(
        self,
        modules: ProjectModuleRegistry | None = None,
        parent=None,
        migrations: ProjectMigrationService | None = None,
    ) -> None:
        super().__init__(parent)
        self._modules = modules or ProjectModuleRegistry()
        self._migrations = migrations or ProjectMigrationService()
        self._codecs = create_core_codec_registry()
        for module in self._modules.enabled():
            module.register_codecs(self._codecs)
        self._active_project: Project | None = None
        self._background_save_repository: ProjectRepository | None = None
        self._background_close_project: Project | None = None
        self.workspace_manager = WorkspaceManager(self, self)

    @property
    def active_project(self) -> Project | None:
        return self._active_project

    def create_project(self, metadata: ProjectMetadata, storage: ProjectStorageAdapter | None = None) -> Project:
        repository = ProjectRepository(storage or InMemoryProjectStorage())
        repository.acquire_lock()
        try:
            repository.configure_codecs(self._codecs)
            descriptors = self._modules.descriptors()
            manifest = ProjectManifest(
                capabilities=frozenset(
                    capability for item in descriptors.values() for capability in item.capabilities_provided
                ),
                enabled_modules=frozenset(descriptors),
                module_schemas={module_id: item.schema_version for module_id, item in descriptors.items()},
            )
            repository.create_core(manifest, metadata)
            return self.open_repository(repository)
        except Exception:
            repository.close()
            raise

    def open_project(self, location: str | Path) -> Project:
        """Ouvre un projet depuis son dossier ou son fichier d'entrée officiel."""
        return self.open_repository(ProjectRepository(JsonProjectStorage(location)))

    def open_repository(self, repository: ProjectRepository) -> Project:
        repository.acquire_lock()
        if self._active_project is not None:
            self.close_project()
        opened: list[tuple[object, ProjectModuleContext]] = []
        try:
            repository.configure_codecs(self._codecs)
            manifest = repository.load_manifest()
            metadata = repository.load_metadata()
            if manifest is None or metadata is None:
                raise ValueError("Projet invalide : manifest ou métadonnées manquants.")
            if manifest.format_name != "carvex":
                raise ValueError("Projet invalide : format logique non pris en charge.")
            if manifest.schema_version > CURRENT_SCHEMA_VERSION:
                raise ValueError("Projet créé avec un schéma plus récent : ouverture lecture seule à implémenter.")
            manifest = self._activate_available_modules(self._migrate_manifest(repository, manifest))
            project = Project(
                manifest=manifest,
                metadata=metadata,
                settings=repository.load_settings() or ProjectSettings(),
                state=repository.load_state() or ProjectState(),
                repository=repository,
                workspaces=repository.load_workspaces(),
            )
            for module in self._modules.enabled(project.manifest.enabled_modules):
                context = ProjectModuleContext(
                    project.manifest.project_id, repository, module.descriptor, project.manifest.capabilities
                )
                if not module.descriptor.capabilities_required <= project.manifest.capabilities:
                    raise ValueError(f"Capabilities manquantes pour le module {module.descriptor.module_id}")
                errors = module.validate(context)
                if errors:
                    raise ValueError(f"Validation module {module.descriptor.module_id} : {'; '.join(errors)}")
                module.initialize(context)
                module.open(context)
                opened.append((module, context))
        except Exception:
            for module, context in reversed(opened):
                module.close(context)
            repository.close()
            raise
        repository.flush()
        self._active_project = project
        self.project_opened.emit(project)
        return project

    def _migrate_manifest(self, repository: ProjectRepository, manifest: ProjectManifest) -> ProjectManifest:
        """Exécute le noyau puis les migrations des modules activés, dans l'ordre."""
        history = list(manifest.migration_history)
        if manifest.schema_version < CURRENT_SCHEMA_VERSION:
            applied = self._migrations.migrate(repository, manifest.schema_version, CURRENT_SCHEMA_VERSION)
            history.extend(f"core:{version - 1}->{version}" for version in applied)
            manifest = replace(manifest, schema_version=CURRENT_SCHEMA_VERSION, migration_history=tuple(history))

        module_schemas = dict(manifest.module_schemas)
        for module in self._modules.enabled(manifest.enabled_modules):
            descriptor = module.descriptor
            if descriptor.module_id not in module_schemas:
                # Les manifests antérieurs à la version modulaire utilisent la
                # version courante comme baseline compatible, sans migration.
                module_schemas[descriptor.module_id] = descriptor.schema_version
                manifest = replace(manifest, module_schemas=module_schemas)
            current = module_schemas[descriptor.module_id]
            if current > descriptor.schema_version:
                raise ValueError(f"Module {descriptor.module_id} plus récent que cette version de CarvEx.")
            if current == descriptor.schema_version:
                continue
            context = ProjectModuleContext(manifest.project_id, repository, descriptor, manifest.capabilities)
            applied = module.migrations().migrate(context, current, descriptor.schema_version)
            module_schemas[descriptor.module_id] = descriptor.schema_version
            history.extend(f"module:{descriptor.module_id}:{version - 1}->{version}" for version in applied)
            manifest = replace(manifest, module_schemas=module_schemas, migration_history=tuple(history))

        repository.save_manifest(manifest)
        return manifest

    def _activate_available_modules(self, manifest: ProjectManifest) -> ProjectManifest:
        """Ajoute sans perte les modules installés aux projets antérieurs.

        Un module déclare ses stores et ses codecs ; l'activation ne matérialise
        aucune donnée. Elle permet notamment à un ancien projet de recevoir son
        store Metadata vide à la première ouverture.
        """
        descriptors = self._modules.descriptors()
        missing = frozenset(descriptors) - manifest.enabled_modules
        if not missing:
            return manifest
        capabilities = set(manifest.capabilities)
        schemas = dict(manifest.module_schemas)
        for module_id in missing:
            descriptor = descriptors[module_id]
            capabilities.update(descriptor.capabilities_provided)
            schemas[module_id] = descriptor.schema_version
        return replace(
            manifest,
            enabled_modules=frozenset((*manifest.enabled_modules, *missing)),
            capabilities=frozenset(capabilities),
            module_schemas=schemas,
        )

    def update_metadata(self, metadata: ProjectMetadata) -> None:
        project = self._require_active()
        project.metadata = metadata
        project.repository.save_metadata(metadata)
        self.project_changed.emit(project)
        self.dirty_changed.emit(True)

    def save_workspace(self, workspace) -> None:
        project = self._require_active()
        project.workspaces[workspace.workspace_id] = workspace
        project.state = replace(project.state, active_workspace_id=workspace.workspace_id)

    @property
    def is_dirty(self) -> bool:
        return bool(self._active_project and self._active_project.repository.is_dirty)

    def log_dirty_state(self, stage: str) -> None:
        """Exporte le diagnostic du backend actif, uniquement en mode performance."""
        if self._active_project is not None:
            self._active_project.repository.log_dirty_state(stage)

    def save_project(self) -> None:
        self._ensure_no_background_save()
        project = self._require_active()
        self._save_modules(project)
        self._persist_core(project)
        project.repository.flush()
        self.dirty_changed.emit(False)

    def begin_background_save(self) -> ProjectRepository | None:
        """Prépare en MainThread un flush exclusif à exécuter hors UI.

        Les modules, les workspaces Qt déjà capturés et les stores restent
        traités ici. Le repository retourné ne doit ensuite plus recevoir
        d'écriture jusqu'à :meth:`finish_background_save`.
        """
        self._ensure_no_background_save()
        project = self._require_active()
        self._save_modules(project)
        self._persist_core(project)
        if not project.repository.is_dirty:
            return None
        project.repository.begin_background_flush()
        self._background_save_repository = project.repository
        if ENABLED:
            LOGGER.info("[Save] background flush prepared close=False")
        return project.repository

    def begin_background_close(self) -> ProjectRepository | None:
        """Prépare un snapshot stable, sans invalider les modules encore visibles."""
        self._ensure_no_background_save()
        project = self._require_active()
        if ENABLED:
            LOGGER.info("[Shutdown] background close preparation dirty=%s", project.repository.is_dirty)
        self._save_modules(project)
        self.project_closing.emit(project)
        self._persist_core(project)
        if not project.repository.is_dirty:
            self._close_modules(project)
            project.repository.flush()
            self._finish_project_close(project)
            return None
        project.repository.begin_background_flush()
        self._background_save_repository = project.repository
        self._background_close_project = project
        if ENABLED:
            LOGGER.info("[Save] background flush prepared close=True")
        return project.repository

    def finish_background_save(self, succeeded: bool) -> bool:
        """Termine l'exclusion de stockage et finalise éventuellement la fermeture.

        Retourne ``True`` si la sauvegarde terminait une fermeture de projet.
        En cas d'échec, le projet et son verrou restent actifs exactement comme
        lors d'un échec de ``close_project`` synchrone.
        """
        repository = self._background_save_repository
        if repository is None:
            raise RuntimeError("Aucune sauvegarde asynchrone active.")
        closing_project = self._background_close_project
        self._background_save_repository = None
        self._background_close_project = None
        if not succeeded:
            repository.end_background_flush()
            if ENABLED:
                LOGGER.info("[Save] background flush failed close=%s", closing_project is not None)
            return closing_project is not None
        if closing_project is not None:
            # Le worker a sérialisé le snapshot complet. Les modules doivent
            # donc rester ouverts jusqu'ici : leurs lookups sont encore appelés
            # par les modèles Qt pendant le dialogue modal.
            if ENABLED:
                LOGGER.info("[Shutdown] modules teardown after background flush")
            try:
                self._close_modules(closing_project)
            finally:
                repository.end_background_flush()
            self._finish_project_close(closing_project)
            return True
        repository.end_background_flush()
        self.dirty_changed.emit(False)
        if ENABLED:
            LOGGER.info("[Save] background flush succeeded close=False")
        return False

    def notify_persistent_change(self) -> None:
        """Point d'orchestration pour les services ayant modifié leur repository."""
        if self.is_dirty:
            self.dirty_changed.emit(True)

    def save_as(self, storage: ProjectStorageAdapter) -> Project:
        """Copie le projet via repositories, jamais via les fichiers de son backend."""
        source = self._require_active()
        self.save_project()
        repository = ProjectRepository(storage)
        repository.acquire_lock()
        try:
            repository.configure_codecs(self._codecs)
            repository.restore_snapshot(source.repository.snapshot())
            repository.flush()
            return self.open_repository(repository)
        except Exception:
            repository.close()
            raise

    def close_project(self, save: bool = True) -> None:
        self._ensure_no_background_save()
        project = self._active_project
        if project is None:
            return
        if ENABLED:
            LOGGER.info("[Shutdown] project teardown save=%s dirty=%s", save, project.repository.is_dirty)
        project.repository.log_dirty_state("close_start")
        if save:
            self._save_modules(project)
        with measure("shutdown.project_closing_signal"), operation("Shutdown", "project_closing_signal"):
            self.project_closing.emit(project)
        project.repository.log_dirty_state("after_project_closing_signal")
        self._close_modules(project)
        if save:
            # Workspace is deliberately excluded from the dirty indicator, but
            # must still survive a normal close. The project lock is the session
            # marker: it is released only after this flush succeeds. Updating
            # ``clean_shutdown`` in the monolithic manifest would otherwise
            # rewrite an unchanged multi-gigabyte project solely for a flag that
            # is not consumed by project recovery.
            self._persist_core(project)
            project.repository.log_dirty_state("after_persist_core")
            with measure("shutdown.repository_flush"), operation("Shutdown", "repository_flush"):
                project.repository.flush()
        self._finish_project_close(project)

    def _save_modules(self, project: Project) -> None:
        with measure("shutdown.modules_save"), operation("Shutdown", "modules_save"):
            for module in self._modules.enabled(project.manifest.enabled_modules):
                context = ProjectModuleContext(
                    project.manifest.project_id,
                    project.repository,
                    module.descriptor,
                    project.manifest.capabilities,
                )
                module.save(context)
                project.repository.log_dirty_state(f"after_module_save:{module.descriptor.module_id}")

    def _close_modules(self, project: Project) -> None:
        with measure("shutdown.modules_close"), operation("Shutdown", "modules_close"):
            for module in reversed(self._modules.enabled(project.manifest.enabled_modules)):
                context = ProjectModuleContext(
                    project.manifest.project_id, project.repository, module.descriptor, project.manifest.capabilities
                )
                module.close(context)
                project.repository.log_dirty_state(f"after_module_close:{module.descriptor.module_id}")

    @staticmethod
    def _persist_core(project: Project) -> None:
        with measure("shutdown.persist_core"), operation("Shutdown", "persist_core"):
            for workspace in project.workspaces.values():
                project.repository.save_workspace(workspace)
            project.repository.save_state(project.state)
        project.repository.log_dirty_state("after_persist_core")

    def _finish_project_close(self, project: Project) -> None:
        self._active_project = None
        with measure("shutdown.project_lock_release"), operation("Shutdown", "project_lock_release"):
            project.repository.close()
        self.dirty_changed.emit(False)
        self.project_closed.emit()

    def _ensure_no_background_save(self) -> None:
        if self._background_save_repository is not None:
            raise RuntimeError("Une sauvegarde du projet est déjà en cours.")

    def _require_active(self) -> Project:
        if self._active_project is None:
            raise RuntimeError("Aucun projet CarvEx actif.")
        return self._active_project
