"""Gestion logique des workspaces, séparée des données d'investigation."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from project.models import Workspace


class WorkspaceManager(QObject):
    workspace_changed = Signal(object)

    def __init__(self, project_manager, parent=None) -> None:
        super().__init__(parent)
        self._project_manager = project_manager

    def current(self) -> Workspace | None:
        project = self._project_manager.active_project
        return project.workspaces.get(project.state.active_workspace_id) if project else None

    def activate(self, workspace_id: str) -> Workspace:
        project = self._project_manager.active_project
        if project is None or workspace_id not in project.workspaces:
            raise KeyError(f"Workspace inconnu : {workspace_id}")
        workspace = project.workspaces[workspace_id]
        self._project_manager.save_workspace(workspace)
        self.workspace_changed.emit(workspace)
        return workspace

    def save(self, workspace: Workspace) -> None:
        self._project_manager.save_workspace(workspace)
        self.workspace_changed.emit(workspace)
