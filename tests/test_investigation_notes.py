from dataclasses import replace
from datetime import timedelta

from investigation.module import InvestigationProjectModule
from investigation.note import InvestigationNote, InvestigationNoteFormat
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from project.manager import ProjectManager
from project.models import ProjectMetadata
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage


def _service(storage=None) -> tuple[ProjectManager, InvestigationService]:
    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    manager = ProjectManager(modules)
    project = manager.create_project(ProjectMetadata("Notes Investigation"), storage)
    service = project.repository.module_repository("investigation", "service")
    assert isinstance(service, InvestigationService)
    return manager, service


def _target(kind: str, identifier: str) -> InvestigationTargetRef:
    return InvestigationTargetRef(kind, identifier)


def _raises(expected_exception, callback) -> None:
    try:
        callback()
    except expected_exception:
        return
    raise AssertionError(f"{expected_exception.__name__} attendu")


def test_note_create_update_and_delete():
    _manager, service = _service()
    target = _target("file", "file-1")
    note = service.create_note("Observation initiale", target_ref=target, author="alice")

    assert service.get_note(note.note_id) == note
    assert service.find_notes_for_target(target) == (note,)

    updated = replace(
        note,
        body="Observation confirmée",
        author="bob",
        updated_at=note.updated_at + timedelta(seconds=1),
    )
    assert service.update_note(updated) == updated
    assert service.find_notes_for_target(target) == (updated,)

    service.delete_note(note.note_id)

    assert service.get_note(note.note_id) is None
    assert service.find_notes_for_target(target) == ()
    assert service.list_notes() == ()


def test_note_ids_and_format_are_validated():
    _manager, service = _service()
    note = service.create_note("Note unique")
    duplicate_id = InvestigationNote(
        note_id=note.note_id,
        target_ref=None,
        body="Duplication",
    )

    _raises(ValueError, lambda: service.manager.create_note(duplicate_id))
    _raises(
        ValueError,
        lambda: InvestigationNote(
            note_id="bad-format",
            target_ref=None,
            body="Format invalide",
            format="markdown",  # type: ignore[arg-type]
        ),
    )


def test_note_indexes_are_reconstructible():
    _manager, service = _service()
    target = _target("investigation_item", "item-1")
    first = service.create_note("Première", target_ref=target, author="alice")
    second = service.create_note("Seconde", target_ref=target, author="bob")
    untargeted = service.create_note("Note sans cible")

    service.manager.rebuild_indexes()

    assert {note.note_id for note in service.find_notes_for_target(target)} == {first.note_id, second.note_id}
    assert {note.note_id for note in service.list_notes()} == {first.note_id, second.note_id, untargeted.note_id}


def test_notes_round_trip_through_json_and_project_reopen(tmp_path):
    root = tmp_path / "notes.carvex"
    first_manager, first_service = _service(JsonProjectStorage(root, create=True))
    created = first_service.create_note(
        "Note persistée",
        target_ref=_target("file", "file-1"),
        format=InvestigationNoteFormat.PLAIN_TEXT,
        author="alice",
    )
    first_manager.save_project()
    first_manager.close_project()

    modules = ProjectModuleRegistry()
    modules.register(InvestigationProjectModule())
    reopened_manager = ProjectManager(modules)
    project = reopened_manager.open_repository(ProjectRepository(JsonProjectStorage(root)))
    service = project.repository.module_repository("investigation", "service")

    assert isinstance(service, InvestigationService)
    assert service.get_note(created.note_id) == created
    assert service.find_notes_for_target(_target("file", "file-1")) == (created,)
