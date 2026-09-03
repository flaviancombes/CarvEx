"""Accès central aux stores du projet ; seul composant autorisé à voir le storage adapter."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from project.codecs import ProjectCodecRegistry
from project.models import ProjectManifest, ProjectMetadata, ProjectSettings, ProjectState, Workspace
from project.storage import ProjectStorageAdapter
from project.stores import ProjectStore
from utils.performance import ENABLED, LOGGER, pipeline_stage

if TYPE_CHECKING:
    pass


class ProjectRepository:
    CORE_NAMESPACE = "core"

    def __init__(self, storage: ProjectStorageAdapter) -> None:
        self._storage = storage
        self._module_repositories: dict[tuple[str, str], object] = {}

    def create_core(self, manifest: ProjectManifest, metadata: ProjectMetadata) -> None:
        self.save_manifest(manifest)
        self.save_metadata(metadata)
        self.save_settings(ProjectSettings())
        self.save_state(ProjectState())
        self.save_workspace(Workspace("default", "Espace principal"))

    def configure_codecs(self, registry: ProjectCodecRegistry) -> None:
        """Configure le backend avant toute lecture sérialisée du projet."""
        self._storage.configure_codecs(registry)

    def acquire_lock(self) -> None:
        """Protège le projet actif avant toute écriture de ses stores."""
        self._storage.acquire_lock()

    def close(self) -> None:
        """Libère le verrou et les ressources du backend de projet."""
        self._storage.close()

    def load_manifest(self) -> ProjectManifest | None:
        return self._storage.read(self.CORE_NAMESPACE, "manifest")

    def save_manifest(self, manifest: ProjectManifest) -> None:
        self._write_if_changed(self.CORE_NAMESPACE, "manifest", manifest)

    def load_metadata(self) -> ProjectMetadata | None:
        return self._storage.read(self.CORE_NAMESPACE, "metadata")

    def save_metadata(self, metadata: ProjectMetadata) -> None:
        self._write_if_changed(self.CORE_NAMESPACE, "metadata", metadata)

    def load_settings(self) -> ProjectSettings | None:
        return self._storage.read(self.CORE_NAMESPACE, "settings")

    def save_settings(self, settings: ProjectSettings) -> None:
        self._write_if_changed(self.CORE_NAMESPACE, "settings", settings)

    def load_state(self) -> ProjectState | None:
        return self._storage.read(self.CORE_NAMESPACE, "state")

    def save_state(self, state: ProjectState) -> None:
        self._write_if_changed(self.CORE_NAMESPACE, "state", state)

    def save_workspace(self, workspace: Workspace) -> None:
        self._write_if_changed("workspaces", workspace.workspace_id, workspace)

    def load_workspaces(self) -> dict[str, Workspace]:
        return {
            key: workspace
            for key in self._storage.keys("workspaces")
            if (workspace := self._storage.read("workspaces", key)) is not None
        }

    def store_for(self, module_id: str, name: str) -> ProjectStore:
        return ProjectStore(self._storage, f"module:{module_id}:{name}")

    def cache_for(self, module_id: str, name: str) -> ProjectStore:
        """Cache reconstructible, séparé des stores métier persistables."""
        return ProjectStore(self._storage, f"cache:{module_id}:{name}")

    def register_module_repository(self, module_id: str, name: str, repository: object) -> None:
        self._module_repositories[module_id, name] = repository

    def module_repository(self, module_id: str, name: str) -> object:
        return self._module_repositories[module_id, name]

    @property
    def is_dirty(self) -> bool:
        return self._storage.is_dirty

    def flush(self) -> None:
        self.log_dirty_state("before_flush")
        with pipeline_stage("ProjectStorage.flush"):
            self._storage.flush()

    def log_dirty_state(self, stage: str) -> None:
        """Journalise les dirty flags sans parcourir les données du projet."""
        if not ENABLED:
            return
        dirty, namespaces, operations = self._storage.dirty_details()
        LOGGER.info(
            "[Storage] dirty_state stage=%s repository=%s storage=%s dirty_namespaces=%s dirty_operations=%s",
            stage,
            self.is_dirty,
            dirty,
            list(namespaces),
            list(operations),
        )

    def _write_if_changed(self, namespace: str, key: str, value: object) -> None:
        """Évite de rendre le projet dirty pour un objet cœur strictement identique."""
        existing = self._storage.read(namespace, key, _MISSING)
        if existing != value:
            self._storage.write(namespace, key, value)

    def snapshot(self):
        return self._storage.snapshot()

    def restore_snapshot(self, snapshot) -> None:
        for namespace, values in snapshot.items():
            for key, value in values.items():
                self._storage.write(namespace, key, value)

    @property
    def physical_root(self) -> Path | None:
        """Expose le répertoire d'un backend local au seul adaptateur de projection.

        Les repositories métier continuent de ne connaître que les stores. Un
        backend non local, tel que le stockage mémoire de tests, n'a pas de
        représentation physique.
        """
        root = getattr(self._storage, "root", None)
        return root if isinstance(root, Path) else None


_MISSING = object()
