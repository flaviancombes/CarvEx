"""Abstractions logiques du projet actif CarvEx."""

from project.codecs import ProjectCodec, ProjectCodecRegistry
from project.locking import ProjectLockedError
from project.manager import ProjectManager
from project.models import (
    Project,
    ProjectManifest,
    ProjectMetadata,
    ProjectSettings,
    ProjectState,
    ReportSourceAuditEntry,
    ReportSourceSnapshot,
    Workspace,
)
from project.modules import ProjectModuleRegistry
from project.repository import ProjectRepository
from project.storage import InMemoryProjectStorage, ProjectStorageAdapter
from project.workspaces import WorkspaceManager

__all__ = (
    "InMemoryProjectStorage",
    "ProjectCodec",
    "ProjectCodecRegistry",
    "Project",
    "ProjectManager",
    "ProjectLockedError",
    "ProjectManifest",
    "ProjectMetadata",
    "ReportSourceSnapshot",
    "ProjectModuleRegistry",
    "ProjectRepository",
    "ProjectSettings",
    "ProjectState",
    "ReportSourceAuditEntry",
    "ProjectStorageAdapter",
    "Workspace",
    "WorkspaceManager",
)
