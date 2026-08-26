"""Lecture rétrocompatible des données produites par un rapport CarvEx."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.file_identity import FILE_IDENTITY_SCHEME, FileIdentityError, assign_file_ids
from project.models import ReportSourceSnapshot


class ReportLoadError(RuntimeError):
    """Le dossier indiqué ne contient pas un rapport CarvEx exploitable."""


@dataclass(frozen=True, slots=True)
class LoadedReport:
    """Référence immuable aux données fournies par le rapport généré."""

    report_path: Path
    payload: dict[str, Any]
    file_identity_scheme: str
    source_snapshot: ReportSourceSnapshot

    @property
    def file_identity_namespace(self) -> None:
        """Compatibilité de lecture : les identités v2 n'utilisent plus de namespace projet."""
        return None

    @property
    def files(self) -> list[dict[str, Any]]:
        files = self.payload.get("files", [])
        return files if isinstance(files, list) else []


class ReportLoader:
    """Privilégie ``report-data.json`` et lit les rapports HTML historiques."""

    DATA_FILENAME = "report-data.json"
    _LEGACY_DATA_PATTERN = re.compile(
        r"const\s+reportData\s*=\s*(?P<payload>\{.*?\})\s*;</script>",
        re.DOTALL,
    )

    @classmethod
    def load(cls, destination: str | Path, file_identity_namespace: str | None = None) -> LoadedReport:
        report_path = cls._find_report(Path(destination))
        try:
            data_path = report_path.with_name(cls.DATA_FILENAME)
            if data_path.is_file():
                payload = cls._read_data_file(data_path)
                snapshot = cls._snapshot_for_file(data_path, payload)
            else:
                raw_report = report_path.read_bytes()
                payload = cls._extract_legacy_payload(raw_report.decode("utf-8"))
                snapshot = cls._snapshot_for_bytes(report_path, raw_report, payload)
        except (OSError, UnicodeDecodeError) as error:
            raise ReportLoadError(f"Impossible de lire le rapport : {report_path}") from error
        try:
            cls._assign_file_identities(payload)
        except FileIdentityError as error:
            raise ReportLoadError(str(error)) from error
        # ``file_identity_namespace`` reste accepté pour ne pas casser les
        # appelants historiques, mais il ne participe plus à l'identité.
        _ = file_identity_namespace
        snapshot = cls._with_evidence_inventory(snapshot, payload)
        return LoadedReport(report_path, payload, FILE_IDENTITY_SCHEME, snapshot)

    @classmethod
    def _find_report(cls, selected_path: Path) -> Path:
        for candidate in (selected_path / "reports" / "index.html", selected_path / "index.html"):
            if candidate.is_file():
                return candidate
        raise ReportLoadError("Aucun rapport CarvEx trouvé. Sélectionnez le dossier de destination ou reports.")

    @staticmethod
    def _read_data_file(data_path: Path) -> dict[str, Any]:
        try:
            with data_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except json.JSONDecodeError as error:
            raise ReportLoadError("Les données JSON du rapport ne sont pas valides.") from error
        if not isinstance(payload, dict):
            raise ReportLoadError("Le jeu de données du rapport doit être un objet JSON.")
        return payload

    @classmethod
    def _extract_legacy_payload(cls, html: str) -> dict[str, Any]:
        match = cls._LEGACY_DATA_PATTERN.search(html)
        if match is None:
            raise ReportLoadError("Les données reportData sont absentes du rapport.")
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise ReportLoadError("Les données reportData ne sont pas valides.") from error
        if not isinstance(payload, dict):
            raise ReportLoadError("Le rapport ne contient pas un objet reportData valide.")
        return payload

    @staticmethod
    def _assign_file_identities(payload: dict[str, Any]) -> None:
        files = payload.get("files", [])
        if not isinstance(files, list):
            raise ReportLoadError("Le rapport contient une liste de fichiers invalide.")
        if not all(isinstance(record, dict) for record in files):
            raise ReportLoadError("Chaque fichier du rapport doit être un objet.")
        assign_file_ids(files)

    @staticmethod
    def _snapshot_for_bytes(report_path: Path, raw_report: bytes, payload: dict[str, Any]) -> ReportSourceSnapshot:
        return ReportLoader._snapshot(report_path, sha256(raw_report).hexdigest(), payload)

    @staticmethod
    def _snapshot_for_file(report_path: Path, payload: dict[str, Any]) -> ReportSourceSnapshot:
        digest = sha256()
        with report_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return ReportLoader._snapshot(report_path, digest.hexdigest(), payload)

    @staticmethod
    def _snapshot(report_path: Path, fingerprint: str, payload: dict[str, Any]) -> ReportSourceSnapshot:
        stat = report_path.stat()
        files = payload.get("files", ())
        return ReportSourceSnapshot(
            fingerprint_sha256=fingerprint,
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            size_bytes=stat.st_size,
            report_version=ReportLoader._report_version(payload),
            file_count=len(files) if isinstance(files, list) else 0,
        )

    @staticmethod
    def _with_evidence_inventory(snapshot: ReportSourceSnapshot, payload: dict[str, Any]) -> ReportSourceSnapshot:
        """Ajoute une empreinte d'inventaire stable malgré le réordonnancement.

        Les ``file_id`` sont calculés avant cet appel à partir de la provenance
        et du SHA-256. Le tri sert uniquement à rendre l'empreinte indépendante
        de la présentation du rapport ; aucun objet preuve n'est dupliqué.
        """
        files = payload["files"]
        digest = sha256()
        for file_id in sorted(str(record["file_id"]) for record in files):
            digest.update(file_id.encode("ascii"))
            digest.update(b"\0")
        return ReportSourceSnapshot(
            fingerprint_sha256=snapshot.fingerprint_sha256,
            modified_at=snapshot.modified_at,
            size_bytes=snapshot.size_bytes,
            report_version=snapshot.report_version,
            file_count=snapshot.file_count,
            evidence_fingerprint_sha256=digest.hexdigest(),
        )

    @staticmethod
    def _report_version(payload: dict[str, Any]) -> str | None:
        for key in ("report_version", "version", "schema_version"):
            value = payload.get(key)
            if isinstance(value, (str, int, float)):
                return str(value)
        return None
