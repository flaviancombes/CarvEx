from __future__ import annotations

import json
from datetime import UTC, datetime

from core.report_loader import ReportLoader
from project.codecs import create_core_codec_registry
from project.models import ProjectMetadata, ReportSourceAuditEntry, ReportSourceSnapshot
from project.repository import ProjectRepository
from project.storage import JsonProjectStorage


def _write_report(root, payload) -> None:
    for index, record in enumerate(payload.get("files", ())):
        record.setdefault("sha256", f"{index + 1:064x}")
        record.setdefault("source_path", f"/photorec/{index}/{record.get('name', 'recovered')}")
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "index.html").write_text(
        f"<script>const reportData = {json.dumps(payload)};</script>",
        encoding="utf-8",
    )


def test_report_loader_captures_fingerprint_date_version_and_file_count(tmp_path):
    _write_report(tmp_path, {"version": "2.1", "files": [{"name": "one"}, {"name": "two"}]})

    report = ReportLoader.load(tmp_path)

    snapshot = report.source_snapshot
    assert len(snapshot.fingerprint_sha256) == 64
    assert snapshot.modified_at.tzinfo is not None
    assert snapshot.report_version == "2.1"
    assert snapshot.file_count == 2
    assert snapshot.size_bytes > 0
    assert len(snapshot.evidence_fingerprint_sha256) == 64


def test_report_snapshot_detects_a_modified_report(tmp_path):
    _write_report(tmp_path, {"version": "1", "files": [{"name": "one"}]})
    original = ReportLoader.load(tmp_path).source_snapshot

    _write_report(tmp_path, {"version": "2", "files": [{"name": "one"}, {"name": "two"}]})
    changed = ReportLoader.load(tmp_path).source_snapshot

    assert not original.matches_content(changed)
    assert changed.report_version == "2"
    assert changed.file_count == 2
    assert not original.matches_evidence_inventory(changed)


def test_report_snapshot_recognizes_a_reordered_inventory_without_accepting_raw_change(tmp_path):
    first = {"name": "one", "sha256": "a" * 64, "source_path": "/photorec/one"}
    second = {"name": "two", "sha256": "b" * 64, "source_path": "/photorec/two"}
    _write_report(tmp_path, {"files": [first, second]})
    original = ReportLoader.load(tmp_path).source_snapshot

    _write_report(tmp_path, {"files": [second, first]})
    reordered = ReportLoader.load(tmp_path).source_snapshot

    assert not original.matches_content(reordered)
    assert original.matches_evidence_inventory(reordered)


def test_report_snapshot_detects_added_removed_and_replaced_evidence(tmp_path):
    first = {"name": "one", "sha256": "a" * 64, "source_path": "/photorec/one"}
    second = {"name": "two", "sha256": "b" * 64, "source_path": "/photorec/two"}
    third = {"name": "three", "sha256": "c" * 64, "source_path": "/photorec/three"}
    _write_report(tmp_path, {"files": [first, second]})
    original = ReportLoader.load(tmp_path).source_snapshot

    _write_report(tmp_path, {"files": [first, second, third]})
    enriched = ReportLoader.load(tmp_path).source_snapshot
    _write_report(tmp_path, {"files": [first]})
    incomplete = ReportLoader.load(tmp_path).source_snapshot
    _write_report(tmp_path, {"files": [first, third]})
    replaced = ReportLoader.load(tmp_path).source_snapshot

    assert not original.matches_evidence_inventory(enriched)
    assert not original.matches_evidence_inventory(incomplete)
    assert not original.matches_evidence_inventory(replaced)


def test_source_snapshot_round_trips_through_project_persistence(tmp_path):
    root = tmp_path / "source.carvex"
    snapshot = ReportSourceSnapshot(
        fingerprint_sha256="a" * 64,
        modified_at=datetime.now(UTC),
        size_bytes=123,
        report_version="1",
        file_count=4,
    )
    repository = ProjectRepository(JsonProjectStorage(root, create=True))
    registry = create_core_codec_registry()
    repository.configure_codecs(registry)
    from project.models import ProjectManifest

    audit_entry = ReportSourceAuditEntry(
        occurred_at=datetime.now(UTC),
        action="source_attached",
        previous_reference=None,
        current_reference="C:/reports/index.html",
        previous_fingerprint_sha256=None,
        current_fingerprint_sha256="a" * 64,
        previous_evidence_fingerprint_sha256=None,
        current_evidence_fingerprint_sha256=None,
        summary="Rapport source rattaché au projet.",
    )
    repository.create_core(
        ProjectManifest(), ProjectMetadata("Projet", source_snapshot=snapshot, source_audit=(audit_entry,))
    )
    repository.flush()

    reopened = ProjectRepository(JsonProjectStorage(root))
    reopened.configure_codecs(registry)

    assert reopened.load_metadata().source_snapshot == snapshot
    assert reopened.load_metadata().source_audit == (audit_entry,)


def test_legacy_project_metadata_without_snapshot_remains_supported():
    registry = create_core_codec_registry()

    metadata = registry.deserialize("dataclass:project.models.ProjectMetadata", {"name": "Projet ancien"})

    assert isinstance(metadata, ProjectMetadata)
    assert metadata.source_snapshot is None
