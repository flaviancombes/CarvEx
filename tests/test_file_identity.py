from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from analysis.artifact_classifier import build_default_classifier
from bookmarks.model import Bookmark
from core.duplicates import DuplicateIndex
from core.file_identity import (
    FILE_IDENTITY_SCHEME,
    FileIdentityError,
    LegacyFileIdentityError,
    assert_project_identity_compatible,
    assign_file_ids,
    file_id_for_record,
)
from core.report_loader import ReportLoader, ReportLoadError
from investigation.case import CaseMembership, CaseMembershipId, InvestigationCaseId
from investigation.collection import CollectionMembership, CollectionMembershipId, InvestigationCollectionId
from investigation.hypothesis import (
    HypothesisMembership,
    HypothesisMembershipId,
    HypothesisRole,
    InvestigationHypothesisId,
)
from investigation.item import InvestigationItem, InvestigationItemId
from investigation.note import InvestigationNote, InvestigationNoteId
from investigation.relation import InvestigationRelation, InvestigationRelationId, InvestigationRelationType
from investigation.target_ref import InvestigationTargetRef
from metadata.base import MetadataGroup, MetadataItem, MetadataResult
from metadata.cache import MetadataCache
from project.codecs import create_core_codec_registry
from project.models import ProjectMetadata
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage
from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.source import FILE_MODIFIED, FILESYSTEM


def _record(source_path: str, digest: str) -> dict[str, str]:
    return {"name": "recup.jpg", "source_path": source_path, "output": "export/recup.jpg", "sha256": digest}


def test_import_identity_is_independent_of_report_order():
    first = [_record("/photorec/a.jpg", "a" * 64), _record("/photorec/b.jpg", "b" * 64)]
    reordered = [dict(first[1]), dict(first[0])]

    assign_file_ids(first)
    assign_file_ids(reordered)

    first_by_source = {record["source_path"]: record["file_id"] for record in first}
    reordered_by_source = {record["source_path"]: record["file_id"] for record in reordered}
    assert first_by_source == reordered_by_source


def test_import_identity_changes_when_content_or_provenance_changes():
    original = _record("/photorec/a.jpg", "a" * 64)
    changed_content = _record("/photorec/a.jpg", "b" * 64)
    changed_provenance = _record("/photorec/moved/a.jpg", "a" * 64)

    assert file_id_for_record(original) != file_id_for_record(changed_content)
    assert file_id_for_record(original) != file_id_for_record(changed_provenance)


def test_import_rejects_ambiguous_duplicate_provenance_and_content():
    records = [_record("/photorec/a.jpg", "a" * 64), _record("/photorec/a.jpg", "a" * 64)]

    with pytest.raises(FileIdentityError, match="même identité"):
        assign_file_ids(records)


def test_report_loader_preserves_identity_through_reorder_and_enrichment(tmp_path):
    report_directory = tmp_path / "reports"
    report_directory.mkdir()
    records = [_record("/photorec/a.jpg", "a" * 64), _record("/photorec/b.jpg", "b" * 64)]
    (report_directory / "index.html").write_text(
        f"<script>const reportData = {json.dumps({'files': records})};</script>", encoding="utf-8"
    )
    first = ReportLoader.load(tmp_path)

    enriched = [dict(records[1], mime="image/jpeg"), dict(records[0], category="Images")]
    (report_directory / "index.html").write_text(
        f"<script>const reportData = {json.dumps({'files': enriched})};</script>", encoding="utf-8"
    )
    second = ReportLoader.load(tmp_path)

    assert first.file_identity_scheme == FILE_IDENTITY_SCHEME
    assert {record["source_path"]: record["file_id"] for record in first.files} == {
        record["source_path"]: record["file_id"] for record in second.files
    }


def test_all_persisted_reference_types_stay_bound_to_the_same_proof_after_report_reorder():
    first = [_record("/photorec/a.jpg", "a" * 64), _record("/photorec/b.jpg", "b" * 64)]
    reordered = [dict(first[1]), dict(first[0])]
    assign_file_ids(first)
    assign_file_ids(reordered)
    file_id = first[0]["file_id"]
    reordered_id = next(record["file_id"] for record in reordered if record["source_path"] == "/photorec/a.jpg")
    target = InvestigationTargetRef("file", file_id)

    bookmark = Bookmark("file", file_id, datetime.now(UTC))
    item = InvestigationItem(InvestigationItemId("item"), "file", file_id)
    note = InvestigationNote(InvestigationNoteId("note"), target, "Observation")
    hypothesis_membership = HypothesisMembership(
        HypothesisMembershipId("hypothesis-membership"),
        InvestigationHypothesisId("hypothesis"),
        target,
        HypothesisRole.SUPPORTS,
    )
    case_membership = CaseMembership(CaseMembershipId("case-membership"), InvestigationCaseId("case"), target)
    collection_membership = CollectionMembership(
        CollectionMembershipId("collection-membership"), InvestigationCollectionId("collection"), target
    )
    relation = InvestigationRelation(
        InvestigationRelationId("relation"),
        target,
        InvestigationTargetRef("item", "other"),
        InvestigationRelationType.RELATED_TO,
    )
    duplicates = DuplicateIndex()
    duplicates.build(reordered)

    class StaticExtractor:
        def extract(self, _record):
            return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM),)

    first_event = TimelineManager((StaticExtractor(),)).events_for(first[0])[0]
    reordered_event = TimelineManager((StaticExtractor(),)).events_for(
        next(record for record in reordered if record["source_path"] == "/photorec/a.jpg")
    )[0]

    assert reordered_id == file_id
    assert bookmark.subject_id == item.subject_id == note.target_ref.target_id == file_id
    assert hypothesis_membership.target_ref == case_membership.target_ref == collection_membership.target_ref == target
    assert relation.source_target == target
    assert duplicates.members_for(file_id) == (file_id,)
    assert first_event.event_id == reordered_event.event_id


def test_report_loader_rejects_records_without_a_safe_identity_material(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "index.html").write_text(
        '<script>const reportData = {"files":[{"name":"legacy.jpg"}]};</script>', encoding="utf-8"
    )

    with pytest.raises(ReportLoadError, match="sha256 et source_path"):
        ReportLoader.load(tmp_path)


def test_metadata_cache_never_falls_back_to_optional_file_values():
    cache = MetadataCache()
    first = {"file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5", "name": "same.jpg"}
    second = {"file_id": "591f7211-a4e1-44f2-b88c-b09f9f052454", "name": "same.jpg"}

    cache.set(first, MetadataResult())

    assert cache.get(second) is None
    with pytest.raises(FileIdentityError):
        cache.get({"name": "same.jpg"})


def test_artifact_cache_isolated_for_files_with_identical_optional_values():
    classifier = build_default_classifier()
    first = {"file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5", "name": "same.jpg", "category": "Images"}
    second = {"file_id": "591f7211-a4e1-44f2-b88c-b09f9f052454", "name": "same.jpg", "category": "Images"}
    with_exif = MetadataResult(groups=(MetadataGroup("EXIF", (MetadataItem("Marque", "Canon"),)),))

    assert classifier.classify(first, with_exif)
    assert classifier.classify(second, MetadataResult())[0].identifier == "image.no_exif"


def test_timeline_cache_and_event_identifiers_are_isolated_by_file_id():
    class StaticExtractor:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, _record):
            self.calls += 1
            return (TimelineEvent(FILE_MODIFIED, datetime(2025, 1, 1, tzinfo=UTC), FILESYSTEM),)

    extractor = StaticExtractor()
    manager = TimelineManager((extractor,))
    first = {"file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5", "name": "same.jpg"}
    second = {"file_id": "591f7211-a4e1-44f2-b88c-b09f9f052454", "name": "same.jpg"}

    first_event = manager.events_for(first)[0]
    second_event = manager.events_for(second)[0]

    assert extractor.calls == 2
    assert first_event.event_id != second_event.event_id


def test_identity_scheme_round_trips_through_project_metadata(tmp_path):
    root = tmp_path / "identity.carvex"
    repository = ProjectRepository(JsonProjectStorage(root, create=True))
    from project.models import ProjectManifest

    repository.configure_codecs(create_core_codec_registry())
    repository.create_core(ProjectManifest(), ProjectMetadata("Projet", file_identity_scheme=FILE_IDENTITY_SCHEME))
    repository.flush()

    reopened = ProjectRepository(JsonProjectStorage(root))
    reopened.configure_codecs(create_core_codec_registry())

    assert reopened.load_metadata().file_identity_scheme == FILE_IDENTITY_SCHEME


def test_legacy_project_metadata_remains_readable_but_unmarked():
    registry = create_core_codec_registry()

    metadata = registry.deserialize("dataclass:project.models.ProjectMetadata", {"name": "Projet antérieur"})

    assert isinstance(metadata, ProjectMetadata)
    assert metadata.file_identity_namespace is None
    assert metadata.file_identity_scheme is None


def test_legacy_position_based_project_is_explicitly_refused_before_any_reference_can_be_remapped():
    with pytest.raises(LegacyFileIdentityError, match="basées sur la position"):
        assert_project_identity_compatible(None, "7e494bb5-e57c-4fc1-8fc3-9d4cbfd2dc60")
