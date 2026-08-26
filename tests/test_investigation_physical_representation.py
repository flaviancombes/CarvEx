from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from investigation.module import InvestigationProjectModule
from investigation.physical_representation import InvestigationPhysicalRepresentationService
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage

FILE_ID = "f4eaa4d1-cf9b-4884-b05b-5c53750636f5"


def _project(root: Path):
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Projection Investigation"), JsonProjectStorage(root, create=True))
    service = project.repository.module_repository("investigation", "service")
    representation = project.repository.module_repository("investigation", "physical_representation")
    assert isinstance(service, InvestigationService)
    assert isinstance(representation, InvestigationPhysicalRepresentationService)
    return manager, service, representation


def _record(path: Path) -> dict[str, str]:
    return {"file_id": FILE_ID, "name": path.name, "output": str(path), "sha256": "a" * 64}


def _only_directory(parent: Path) -> Path:
    return next(item for item in parent.iterdir() if item.is_dir())


def test_case_and_collection_are_projected_with_managed_file_references(tmp_path):
    _manager, service, representation = _project(tmp_path / "case.carvex")
    evidence = tmp_path / "evidence.jpg"
    evidence.write_bytes(b"evidence")
    representation.set_file_records([_record(evidence)])
    case = service.create_case("Identification")
    collection = service.create_collection("Documents")
    item = service.create_item("file", FILE_ID, title="Carte identité")
    service.add_to_case(case.case_id, InvestigationTargetRef("item", str(item.item_id)))
    service.add_to_collection(collection.collection_id, InvestigationTargetRef("item", str(item.item_id)))

    assert representation.root is not None
    case_directory = _only_directory(representation.root / "Cases")
    collection_directory = _only_directory(representation.root / "Collections")
    assert (case_directory / representation.MARKER_NAME).is_file()
    assert (collection_directory / representation.MARKER_NAME).is_file()
    assert any(entry.name.startswith("evidence") for entry in case_directory.iterdir())
    assert any(entry.name.startswith("evidence") for entry in collection_directory.iterdir())
    assert evidence.read_bytes() == b"evidence"


def test_rename_external_rename_and_logical_delete_are_synchronised(tmp_path):
    _manager, service, representation = _project(tmp_path / "rename.carvex")
    case = service.create_case("Initial")
    assert representation.root is not None
    parent = representation.root / "Cases"
    directory = _only_directory(parent)

    service.update_case(replace(case, title="Renommée"))
    directory = _only_directory(parent)
    assert directory.name.startswith("Renommée")

    external = parent / f"Externe [{case.case_id}]"
    directory.replace(external)
    representation.synchronize()
    assert service.get_case(case.case_id).title == "Externe"

    service.delete_case(case.case_id)
    assert not external.exists()


def test_membership_removal_removes_only_its_managed_reference(tmp_path):
    _manager, service, representation = _project(tmp_path / "move.carvex")
    evidence = tmp_path / "evidence.jpg"
    evidence.write_bytes(b"evidence")
    representation.set_file_records([_record(evidence)])
    collection = service.create_collection("A vérifier")
    item = service.create_item("file", FILE_ID)
    target = InvestigationTargetRef("item", str(item.item_id))
    service.add_to_collection(collection.collection_id, target)
    assert representation.root is not None
    directory = _only_directory(representation.root / "Collections")
    assert any(entry.name.startswith("evidence") for entry in directory.iterdir())

    service.remove_from_collection(collection.collection_id, target)

    assert not any(entry.name.startswith("evidence") for entry in directory.iterdir())
    assert evidence.exists()


def test_logical_delete_preserves_a_directory_containing_unmanaged_content(tmp_path):
    _manager, service, representation = _project(tmp_path / "protected.carvex")
    case = service.create_case("À conserver")
    assert representation.root is not None
    directory = _only_directory(representation.root / "Cases")
    unmanaged = directory / "note-utilisateur.txt"
    unmanaged.write_text("Ne pas supprimer", encoding="utf-8")

    service.delete_case(case.case_id)

    assert directory.exists()
    assert unmanaged.is_file()
    assert (directory / representation.MARKER_NAME).is_file()


def test_reference_fallback_is_used_when_symbolic_links_are_not_available(tmp_path, monkeypatch):
    _manager, service, representation = _project(tmp_path / "fallback.carvex")
    evidence = tmp_path / "evidence.jpg"
    evidence.write_bytes(b"evidence")
    representation.set_file_records([_record(evidence)])
    monkeypatch.setattr(
        "investigation.physical_representation.os.symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("denied")),
    )
    collection = service.create_collection("Fallback")
    service.add_to_collection(collection.collection_id, InvestigationTargetRef("file", FILE_ID))

    assert representation.root is not None
    directory = _only_directory(representation.root / "Collections")
    assert any(entry.name.endswith(representation.REFERENCE_SUFFIX) for entry in directory.iterdir())


def test_unmarked_reference_suffix_is_never_removed(tmp_path):
    _manager, service, representation = _project(tmp_path / "unmarked-reference.carvex")
    case = service.create_case("Conserver")
    assert representation.root is not None
    directory = _only_directory(representation.root / "Cases")
    unmanaged = directory / "note.carvex-reference"
    unmanaged.write_text("donnÃ©e utilisateur", encoding="utf-8")

    service.delete_case(case.case_id)

    assert unmanaged.is_file()


def test_projection_is_restored_after_project_reopen_and_io_errors_are_non_destructive(tmp_path, monkeypatch):
    root = tmp_path / "reopen.carvex"
    manager, service, representation = _project(root)
    evidence = tmp_path / "evidence.jpg"
    evidence.write_bytes(b"evidence")
    representation.set_file_records([_record(evidence)])
    case = service.create_case("Persistante")
    collection = service.create_collection("Preuves")
    service.add_to_collection(collection.collection_id, InvestigationTargetRef("file", FILE_ID))
    manager.save_project()
    manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    reopened_service = project.repository.module_repository("investigation", "service")
    reopened_representation = project.repository.module_repository("investigation", "physical_representation")
    assert isinstance(reopened_service, InvestigationService)
    assert isinstance(reopened_representation, InvestigationPhysicalRepresentationService)
    assert reopened_representation.root is not None
    assert _only_directory(reopened_representation.root / "Cases").name.endswith(f"[{case.case_id}]")
    collection_directory = _only_directory(reopened_representation.root / "Collections")
    assert any(entry.name.startswith("evidence") for entry in collection_directory.iterdir())

    monkeypatch.setattr(
        "investigation.physical_representation.Path.mkdir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk error")),
    )
    result = reopened_representation.synchronize()

    assert result.warnings
    assert reopened_service.get_case(case.case_id) is not None
