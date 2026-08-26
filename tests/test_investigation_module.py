from investigation.module import InvestigationProjectModule
from investigation.repository import InvestigationRepository
from investigation.service import InvestigationService
from project.manager import ProjectManager
from project.models import ProjectManifest, ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage


def test_investigation_module_is_declared_and_opened_with_the_project():
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    project_manager = ProjectManager(modules)

    project = project_manager.create_project(ProjectMetadata("Investigation test"))
    repository = project.repository.module_repository("investigation", "repository")
    service = project.repository.module_repository("investigation", "service")

    assert project.has_capability("investigation")
    assert isinstance(repository, InvestigationRepository)
    assert isinstance(service, InvestigationService)
    assert repository.store_names == InvestigationRepository.STORE_NAMES
    assert service.is_open

    project_manager.close_project()

    assert not service.is_open


def test_investigation_repository_rejects_unknown_store_names():
    from project.stores import ProjectStore

    stores = {name: ProjectStore(InMemoryProjectStorage(), name) for name in InvestigationRepository.STORE_NAMES}
    stores["unknown"] = ProjectStore(InMemoryProjectStorage(), "unknown")

    try:
        InvestigationRepository(stores)
    except ValueError:
        pass
    else:
        raise AssertionError("Le repository doit refuser les stores non déclarés.")


def test_investigation_service_is_reopened_after_a_project_save_and_reopen():
    storage = InMemoryProjectStorage()
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    first_manager = ProjectManager(modules)

    project = first_manager.create_project(ProjectMetadata("Cycle Investigation"), storage)
    repository = project.repository
    first_manager.save_project()
    first_manager.close_project()

    second_manager = ProjectManager(modules)
    reopened = second_manager.open_repository(repository)
    service = reopened.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.is_open


def test_opening_a_project_without_tag_assignments_initializes_the_logical_store():
    storage = InMemoryProjectStorage()
    repository = ProjectRepository(storage)
    legacy_manifest = ProjectManifest(
        capabilities=frozenset({"investigation"}),
        enabled_modules=frozenset({"investigation"}),
        module_schemas={"investigation": 1},
    )
    repository.create_core(legacy_manifest, ProjectMetadata("Projet antérieur aux tags"))
    repository.flush()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.open_repository(repository)
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.list_tags() == ()
