"""Lecture des données déjà produites par le rapport CarvEx."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


class ReportLoadError(RuntimeError):
    """Le dossier indiqué ne contient pas un rapport CarvEx exploitable."""


@dataclass(frozen=True, slots=True)
class LoadedReport:
    """Référence immuable aux données fournies par le rapport généré."""

    report_path: Path
    payload: dict[str, Any]

    @property
    def files(self) -> list[dict[str, Any]]:
        files = self.payload.get("files", [])
        return files if isinstance(files, list) else []


class ReportLoader:
    """Localise et lit un ``reports/index.html`` existant, sans l'altérer."""

    _DATA_PATTERN = re.compile(
        r"const\s+reportData\s*=\s*(?P<payload>\{.*?\})\s*;</script>",
        re.DOTALL,
    )

    @classmethod
    def load(cls, destination: str | Path) -> LoadedReport:
        report_path = cls._find_report(Path(destination))
        try:
            html = report_path.read_text(encoding="utf-8")
            payload = cls._extract_payload(html)
        except OSError as error:
            raise ReportLoadError(f"Impossible de lire le rapport : {report_path}") from error
        return LoadedReport(report_path=report_path, payload=payload)

    @classmethod
    def _find_report(cls, selected_path: Path) -> Path:
        for candidate in (selected_path / "reports" / "index.html", selected_path / "index.html"):
            if candidate.is_file():
                return candidate
        raise ReportLoadError(
            "Aucun rapport CarvEx trouvé. Sélectionnez le dossier de destination "
            "ou son sous-dossier reports."
        )

    @classmethod
    def _extract_payload(cls, html: str) -> dict[str, Any]:
        match = cls._DATA_PATTERN.search(html)
        if match is None:
            raise ReportLoadError("Les données reportData sont absentes du rapport.")
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise ReportLoadError("Les données reportData ne sont pas valides.") from error
        if not isinstance(payload, dict):
            raise ReportLoadError("Le rapport ne contient pas un objet reportData valide.")
        return payload
