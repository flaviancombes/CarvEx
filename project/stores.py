"""Stores nommés du projet : aucune dépendance aux fichiers ou à SQLite."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from project.storage import ProjectStorageAdapter


class ProjectStore:
    def __init__(self, storage: ProjectStorageAdapter, namespace: str) -> None:
        self._storage = storage
        self.namespace = namespace

    def get(self, key: str, default: Any = None) -> Any:
        return self._storage.read(self.namespace, key, default)

    def set(self, key: str, value: Any) -> None:
        self._storage.write(self.namespace, key, value)

    def delete(self, key: str) -> None:
        self._storage.delete(self.namespace, key)

    def keys(self) -> Iterable[str]:
        """Énumère les clés du namespace sans exposer le storage adapter."""
        return self._storage.keys(self.namespace)
