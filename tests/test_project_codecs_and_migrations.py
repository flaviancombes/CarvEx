"""Tests de l'infrastructure extensible de codecs et migrations de projet."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from project.codecs import ProjectCodecRegistry, dataclass_codec
from project.manager import ProjectManager
from project.migrations import ModuleMigrationService, ProjectMigrationService
from project.models import ProjectManifest, ProjectMetadata
from project.modules import ModuleDescriptor, ProjectModule, ProjectModuleContext, ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage, JsonProjectStorage


@dataclass(frozen=True, slots=True)
class _SampleValue:
    value: str


class _MigratingModule(ProjectModule):
    def __init__(self, module_id: str, schema_version: int, migrations: ModuleMigrationService) -> None:
        self._descriptor = ModuleDescriptor(
            module_id=module_id,
            schema_version=schema_version,
            store_names=frozenset({"migration_markers"}),
        )
        self._migrations = migrations

    @property
    def descriptor(self) -> ModuleDescriptor:
        return self._descriptor

    def migrations(self) -> ModuleMigrationService:
        return self._migrations


def _module_migrations(module_id: str, target_version: int) -> tuple[ModuleMigrationService, list[str]]:
    migrations = ModuleMigrationService(module_id)
    applied: list[str] = []
    for version in range(target_version):

        def step(context: ProjectModuleContext, version: int = version) -> None:
            applied.append(f"{context.descriptor.module_id}:{version}")
            context.store("migration_markers").set(str(version), "done")

        migrations.register(version, step)
    return migrations, applied


def test_registered_codec_round_trips_through_json_storage(tmp_path):
    root = tmp_path / "codecs.carvex"
    registry = ProjectCodecRegistry()
    registry.register(dataclass_codec("sample:value", _SampleValue))
    storage = JsonProjectStorage(root, create=True)
    storage.configure_codecs(registry)
    storage.write("samples", "one", _SampleValue("ok"))
    storage.flush()

    reopened = JsonProjectStorage(root)
    reopened.configure_codecs(registry)

    assert reopened.read("samples", "one") == _SampleValue("ok")


def test_storage_has_no_direct_import_of_business_modules():
    source = (Path(__file__).parents[1] / "project" / "storage.py").read_text(encoding="utf-8")

    assert "from investigation" not in source
    assert "from bookmarks" not in source
    assert "import investigation" not in source
    assert "import bookmarks" not in source


def test_opening_an_old_project_applies_core_migration_automatically():
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(ProjectManifest(schema_version=0), ProjectMetadata("Projet ancien"))
    migrations = ProjectMigrationService()
    migrations.register(0, lambda repo: repo.store_for("core", "migration_markers").set("0", "done"))

    project = ProjectManager(migrations=migrations).open_repository(repository)

    assert project.manifest.schema_version == 1
    assert project.manifest.migration_history == ("core:0->1",)
    assert repository.store_for("core", "migration_markers").get("0") == "done"


def test_module_migrations_are_incremental_idempotent_and_ordered():
    alpha_migrations, alpha_applied = _module_migrations("alpha", 2)
    beta_migrations, beta_applied = _module_migrations("beta", 2)
    modules = ProjectModuleRegistry()
    modules.register(_MigratingModule("alpha", 2, alpha_migrations))
    modules.register(_MigratingModule("beta", 2, beta_migrations))
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(
        ProjectManifest(
            enabled_modules=frozenset({"alpha", "beta"}),
            module_schemas={"alpha": 0, "beta": 1},
        ),
        ProjectMetadata("Migrations modules"),
    )

    manager = ProjectManager(modules)
    project = manager.open_repository(repository)

    assert alpha_applied == ["alpha:0", "alpha:1"]
    assert beta_applied == ["beta:1"]
    assert project.manifest.module_schemas == {"alpha": 2, "beta": 2}
    assert project.manifest.migration_history == (
        "module:alpha:0->1",
        "module:alpha:1->2",
        "module:beta:1->2",
    )

    manager.close_project()
    ProjectManager(modules).open_repository(repository)

    assert alpha_applied == ["alpha:0", "alpha:1"]
    assert beta_applied == ["beta:1"]


def test_legacy_manifest_without_module_schema_opens_with_a_compatible_baseline():
    migrations, applied = _module_migrations("alpha", 2)
    modules = ProjectModuleRegistry()
    modules.register(_MigratingModule("alpha", 2, migrations))
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(
        ProjectManifest(enabled_modules=frozenset({"alpha"})),
        ProjectMetadata("Manifest antérieur aux versions de modules"),
    )

    project = ProjectManager(modules).open_repository(repository)

    assert project.manifest.module_schemas == {"alpha": 2}
    assert applied == []


def test_newer_module_schema_is_rejected_without_running_a_migration():
    migrations, applied = _module_migrations("alpha", 2)
    modules = ProjectModuleRegistry()
    modules.register(_MigratingModule("alpha", 2, migrations))
    repository = ProjectRepository(InMemoryProjectStorage())
    repository.create_core(
        ProjectManifest(enabled_modules=frozenset({"alpha"}), module_schemas={"alpha": 3}),
        ProjectMetadata("Projet plus récent"),
    )

    try:
        ProjectManager(modules).open_repository(repository)
    except ValueError:
        pass
    else:
        raise AssertionError("Un module plus récent doit être refusé.")

    assert applied == []
