"""Registre déclaratif des modules de projet et de leur cycle de vie."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from project.codecs import ProjectCodecRegistry
    from project.migrations import ModuleMigrationService
    from project.repository import ProjectRepository


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    module_id: str
    schema_version: int
    capabilities_provided: frozenset[str] = frozenset()
    capabilities_required: frozenset[str] = frozenset()
    dependencies: frozenset[str] = frozenset()
    store_names: frozenset[str] = frozenset()
    cache_names: frozenset[str] = frozenset()


@dataclass(slots=True)
class ProjectModuleContext:
    project_id: str
    repository: ProjectRepository
    descriptor: ModuleDescriptor
    capabilities: frozenset[str]

    def store(self, name: str):
        return self.repository.store_for(self.descriptor.module_id, name)

    def cache(self, name: str):
        return self.repository.cache_for(self.descriptor.module_id, name)

    def register_repository(self, name: str, repository: object) -> None:
        self.repository.register_module_repository(self.descriptor.module_id, name, repository)


class ProjectModule(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> ModuleDescriptor: ...

    def initialize(self, context: ProjectModuleContext) -> None:  # noqa: B027 - Hook optionnel de cycle de vie.
        """Crée les stores/repositories logiques requis par le module."""

    def register_codecs(self, registry: ProjectCodecRegistry) -> None:  # noqa: B027 - Hook optionnel de cycle de vie.
        """Enregistre les codecs de persistance propres au module."""

    def migrations(self) -> ModuleMigrationService:
        """Retourne les migrations incrémentales du schéma du module."""
        from project.migrations import ModuleMigrationService

        return ModuleMigrationService(self.descriptor.module_id)

    def open(self, context: ProjectModuleContext) -> None:  # noqa: B027 - Hook optionnel de cycle de vie.
        """Ouvre les ressources légères après validation du projet."""

    def close(self, context: ProjectModuleContext) -> None:  # noqa: B027 - Hook optionnel de cycle de vie.
        """Libère ou synchronise les ressources du module."""

    def validate(self, context: ProjectModuleContext) -> tuple[str, ...]:
        return ()

    def save(self, context: ProjectModuleContext) -> None:  # noqa: B027 - Hook optionnel de cycle de vie.
        """Prépare les données du module avant le flush centralisé du projet."""


class ProjectModuleRegistry:
    """Connaît les modules enregistrés ; ProjectManager ne les connaît pas individuellement."""

    def __init__(self) -> None:
        self._modules: dict[str, ProjectModule] = {}

    def register(self, module: ProjectModule) -> None:
        descriptor = module.descriptor
        if descriptor.module_id in self._modules:
            raise ValueError(f"Module déjà enregistré : {descriptor.module_id}")
        self._modules[descriptor.module_id] = module

    def enabled(self, module_ids: frozenset[str] | None = None) -> tuple[ProjectModule, ...]:
        selected = module_ids or frozenset(self._modules)
        pending = {module_id for module_id in selected if module_id in self._modules}
        ordered: list[ProjectModule] = []
        while pending:
            ready = sorted(
                module_id
                for module_id in pending
                if self._modules[module_id].descriptor.dependencies <= (selected - pending)
            )
            if not ready:
                raise ValueError(f"Dépendances de modules non résolues : {sorted(pending)}")
            for module_id in ready:
                pending.remove(module_id)
                ordered.append(self._modules[module_id])
        return tuple(ordered)

    def descriptors(self) -> Mapping[str, ModuleDescriptor]:
        return {module_id: module.descriptor for module_id, module in self._modules.items()}
