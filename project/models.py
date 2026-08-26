"""Agrégats métier légers du projet, indépendants de tout support physique."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from project.repository import ProjectRepository


CURRENT_SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    format_name: str = "carvex"
    project_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = CURRENT_SCHEMA_VERSION
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    created_with: str = "CarvEx"
    last_opened_with: str = "CarvEx"
    minimum_supported_version: str = "1"
    compatibility_level: str = "read_write"
    capabilities: frozenset[str] = frozenset()
    enabled_modules: frozenset[str] = frozenset()
    module_schemas: Mapping[str, int] = field(default_factory=dict)
    migration_history: tuple[str, ...] = ()
    clean_shutdown: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_schemas", MappingProxyType(dict(self.module_schemas)))


@dataclass(frozen=True, slots=True)
class ReportSourceSnapshot:
    """Empreinte vérifiable du rapport externe auquel un projet est rattaché."""

    fingerprint_sha256: str
    modified_at: datetime
    size_bytes: int
    report_version: str | None = None
    file_count: int = 0
    evidence_fingerprint_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fingerprint_sha256, str)
            or len(self.fingerprint_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.fingerprint_sha256.lower())
        ):
            raise ValueError("L'empreinte SHA-256 du rapport est invalide.")
        if not isinstance(self.modified_at, datetime) or self.modified_at.tzinfo is None:
            raise ValueError("La date du rapport doit contenir un fuseau horaire.")
        if self.size_bytes < 0 or self.file_count < 0:
            raise ValueError("La taille et le nombre de fichiers du rapport doivent être positifs.")
        if self.evidence_fingerprint_sha256 is not None and (
            len(self.evidence_fingerprint_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.evidence_fingerprint_sha256.lower())
        ):
            raise ValueError("L'empreinte d'inventaire des preuves est invalide.")

    def matches_content(self, other: ReportSourceSnapshot) -> bool:
        """Compare uniquement le contenu : une copie identique reste valide."""
        return self.fingerprint_sha256 == other.fingerprint_sha256

    def matches_evidence_inventory(self, other: ReportSourceSnapshot) -> bool:
        """Compare l'inventaire canonique, indépendant de l'ordre du rapport.

        Les anciens snapshots sans empreinte d'inventaire restent traités de
        façon conservatrice : seule l'égalité exacte du rapport les valide.
        """
        if self.evidence_fingerprint_sha256 is None or other.evidence_fingerprint_sha256 is None:
            return self.matches_content(other)
        return (
            self.file_count == other.file_count
            and self.evidence_fingerprint_sha256 == other.evidence_fingerprint_sha256
        )


@dataclass(frozen=True, slots=True)
class ReportSourceAuditEntry:
    """Trace synthétique d'un rattachement ou remplacement de rapport source."""

    occurred_at: datetime
    action: str
    previous_reference: str | None
    current_reference: str | None
    previous_fingerprint_sha256: str | None
    current_fingerprint_sha256: str
    previous_evidence_fingerprint_sha256: str | None
    current_evidence_fingerprint_sha256: str | None
    summary: str


@dataclass(frozen=True, slots=True)
class ProjectMetadata:
    name: str
    source_reference: str | None = None
    file_identity_namespace: str | None = None
    file_identity_scheme: str | None = None
    source_snapshot: ReportSourceSnapshot | None = None
    source_audit: tuple[ReportSourceAuditEntry, ...] = ()
    description: str | None = None
    investigator: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    values: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class Workspace:
    workspace_id: str
    name: str
    active_tab: str = "files_view"
    window_geometry: bytes | None = None
    splitter_sizes: tuple[int, ...] = ()
    header_states: Mapping[str, bytes] = field(default_factory=dict)
    columns_by_view: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    sort_by_view: Mapping[str, tuple[int, str]] = field(default_factory=dict)
    filters_by_view: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    searches_by_view: Mapping[str, str] = field(default_factory=dict)
    opened_panels: frozenset[str] = frozenset()
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns_by_view", MappingProxyType(dict(self.columns_by_view)))
        object.__setattr__(self, "header_states", MappingProxyType(dict(self.header_states)))
        object.__setattr__(self, "sort_by_view", MappingProxyType(dict(self.sort_by_view)))
        object.__setattr__(self, "filters_by_view", MappingProxyType(dict(self.filters_by_view)))
        object.__setattr__(self, "searches_by_view", MappingProxyType(dict(self.searches_by_view)))


@dataclass(frozen=True, slots=True)
class ProjectState:
    active_workspace_id: str = "default"
    module_activation_state: Mapping[str, bool] = field(default_factory=dict)
    last_clean_shutdown: bool = True
    recovery_state: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_activation_state", MappingProxyType(dict(self.module_activation_state)))


@dataclass(slots=True)
class Project:
    """Projet logique actif : jamais un chemin ou un format de stockage."""

    manifest: ProjectManifest
    metadata: ProjectMetadata
    settings: ProjectSettings
    state: ProjectState
    repository: ProjectRepository
    workspaces: dict[str, Workspace]

    def has_capability(self, capability: str) -> bool:
        return capability in self.manifest.capabilities
