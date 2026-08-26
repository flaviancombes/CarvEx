"""Infrastructure de migrations versionnées des schémas logiques de projet."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from project.repository import ProjectRepository

if TYPE_CHECKING:
    from project.modules import ProjectModuleContext

MigrationStep = Callable[[ProjectRepository], None]


class ProjectMigrationService:
    def __init__(self) -> None:
        self._steps: dict[int, MigrationStep] = {}

    def register(self, from_version: int, step: MigrationStep) -> None:
        if from_version < 0:
            raise ValueError("Une version de migration ne peut pas être négative.")
        if from_version in self._steps:
            raise ValueError(f"Migration globale déjà déclarée : {from_version}.")
        self._steps[from_version] = step

    def migrate(self, repository: ProjectRepository, current: int, target: int) -> tuple[int, ...]:
        applied: list[int] = []
        while current < target:
            step = self._steps.get(current)
            if step is None:
                raise ValueError(f"Migration manquante : {current} vers {current + 1}")
            step(repository)
            applied.append(current + 1)
            current += 1
        return tuple(applied)


ModuleMigrationStep = Callable[["ProjectModuleContext"], None]


class ModuleMigrationService:
    """Migrations incrémentales d'un module, isolées du noyau projet."""

    def __init__(self, module_id: str) -> None:
        self._module_id = module_id
        self._steps: dict[int, ModuleMigrationStep] = {}

    @property
    def module_id(self) -> str:
        return self._module_id

    def register(self, from_version: int, step: ModuleMigrationStep) -> None:
        if from_version < 0:
            raise ValueError("Une version de migration ne peut pas être négative.")
        if from_version in self._steps:
            raise ValueError(f"Migration déjà déclarée : {self._module_id} {from_version}.")
        self._steps[from_version] = step

    def migrate(self, context: ProjectModuleContext, current: int, target: int) -> tuple[int, ...]:
        if context.descriptor.module_id != self._module_id:
            raise ValueError("Une migration doit être exécutée dans son propre module.")
        applied: list[int] = []
        while current < target:
            step = self._steps.get(current)
            if step is None:
                raise ValueError(f"Migration de module manquante : {self._module_id} {current} vers {current + 1}")
            step(context)
            applied.append(current + 1)
            current += 1
        return tuple(applied)
