"""Projection physique sûre de l'organisation Investigation.

La projection n'est jamais une source de données de preuve : elle ne crée que
des dossiers gérés et des liens vers les fichiers exportés. Les commandes
Investigation restent la source de vérité ; la synchronisation sert à rendre
leur structure visible et à réparer une projection interrompue.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from core.file_identity import FileIdentityError, require_file_id
from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.events import EventBus, EventType, InvestigationEvent
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PhysicalSyncResult:
    """Diagnostic non persistant d'une synchronisation de représentation."""

    created: int = 0
    renamed: int = 0
    removed: int = 0
    references_created: int = 0
    warnings: tuple[str, ...] = ()


class InvestigationPhysicalRepresentationService:
    """Maintient ``Investigation/`` sans modifier fichiers ou données métier.

    Les dossiers peuvent être renommés manuellement : lors de la prochaine
    synchronisation, le titre logique est réconcilié à partir de leur suffixe
    d'identité stable. Les suppressions externes sont réparées, jamais
    répercutées vers le domaine, afin de protéger l'enquête.
    """

    ROOT_NAME = "Investigation"
    CASES_NAME = "Cases"
    COLLECTIONS_NAME = "Collections"
    MARKER_NAME = ".carvex-investigation.json"
    REFERENCE_SUFFIX = ".carvex-reference"
    _INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    def __init__(self, service: InvestigationService, project_root: Path | None) -> None:
        self._service = service
        self._project_root = project_root
        self._file_paths: dict[str, Path] = {}
        self._file_records_available = False
        self._bus: EventBus | None = None
        self._syncing = False
        self._last_result = PhysicalSyncResult()

    @property
    def is_available(self) -> bool:
        return self._project_root is not None

    @property
    def root(self) -> Path | None:
        return self._project_root / self.ROOT_NAME if self._project_root is not None else None

    @property
    def last_result(self) -> PhysicalSyncResult:
        return self._last_result

    def open(self) -> PhysicalSyncResult:
        event_bus = self._service.event_bus
        if event_bus is not None:
            self._bus = event_bus
            event_bus.subscribe(self._on_event)
        return self.synchronize()

    def close(self) -> None:
        if self._bus is not None:
            self._bus.unsubscribe(self._on_event)
        self._bus = None

    def set_file_records(self, records: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]]) -> PhysicalSyncResult:
        """Injecte les chemins des fichiers déjà chargés, sans les recopier."""
        self._file_paths = {}
        self._file_records_available = True
        for record in records:
            try:
                file_id = require_file_id(record)
            except FileIdentityError:
                continue
            for path_field in ("output", "source_path"):
                value = record.get(path_field)
                if value:
                    self._file_paths[file_id] = Path(str(value))
                    break
        return self.synchronize()

    def synchronize(self, *, reconcile_external: bool = True) -> PhysicalSyncResult:
        """Répare de manière idempotente les dossiers et références gérés."""
        if not self.is_available or self.root is None:
            self._last_result = PhysicalSyncResult()
            return self._last_result
        if self._syncing:
            return self._last_result
        self._syncing = True
        try:
            counters = _Counters()
            try:
                self._ensure_root()
                self._synchronize_containers("case", counters, reconcile_external)
                self._synchronize_containers("collection", counters, reconcile_external)
            except OSError as error:
                message = f"Synchronisation Investigation interrompue : {error}"
                LOGGER.warning(message)
                counters.warnings.append(message)
            self._last_result = counters.result()
            return self._last_result
        finally:
            self._syncing = False

    def _on_event(self, event) -> None:
        if self._syncing or not isinstance(event, InvestigationEvent):
            return
        if event.event_type in {
            EventType.CASE_CREATED,
            EventType.CASE_UPDATED,
            EventType.CASE_DELETED,
            EventType.COLLECTION_CREATED,
            EventType.COLLECTION_UPDATED,
            EventType.COLLECTION_DELETED,
            EventType.MEMBERSHIP_ADDED,
            EventType.MEMBERSHIP_REMOVED,
        }:
            self.synchronize(
                reconcile_external=event.event_type not in {EventType.CASE_UPDATED, EventType.COLLECTION_UPDATED}
            )

    def _ensure_root(self) -> None:
        assert self.root is not None
        (self.root / self.CASES_NAME).mkdir(parents=True, exist_ok=True)
        (self.root / self.COLLECTIONS_NAME).mkdir(parents=True, exist_ok=True)

    def _synchronize_containers(self, kind: str, counters: _Counters, reconcile_external: bool) -> None:
        desired = self._containers(kind)
        known_ids = {identifier for identifier, _title in desired}
        for identifier, title in desired:
            directory = self._find_container_directory(kind, identifier)
            if directory is None:
                directory = self._container_parent(kind) / self._directory_name(title, identifier)
                directory.mkdir(parents=True, exist_ok=True)
                self._write_marker(directory, kind, identifier)
                counters.created += 1
            else:
                external_title = self._title_from_directory(directory.name, identifier)
                if reconcile_external and external_title is not None and external_title != title:
                    self._update_title_from_directory(kind, identifier, external_title)
                    title = external_title
                expected = self._container_parent(kind) / self._directory_name(title, identifier)
                if directory != expected:
                    directory.replace(expected)
                    directory = expected
                    counters.renamed += 1
            self._synchronize_references(directory, kind, identifier, counters)

        for directory, marker in self._managed_directories(kind):
            if marker["id"] not in known_ids and self._remove_directory_if_safe(directory):
                counters.removed += 1

    def _containers(self, kind: str) -> tuple[tuple[str, str], ...]:
        if kind == "case":
            return tuple((str(value.case_id), value.title) for value in self._service.list_cases())
        return tuple((str(value.collection_id), value.title) for value in self._service.list_collections())

    def _container_parent(self, kind: str) -> Path:
        assert self.root is not None
        return self.root / (self.CASES_NAME if kind == "case" else self.COLLECTIONS_NAME)

    def _find_container_directory(self, kind: str, identifier: str) -> Path | None:
        for directory, marker in self._managed_directories(kind):
            if marker["id"] == identifier:
                return directory
        return None

    def _managed_directories(self, kind: str):
        parent = self._container_parent(kind)
        if not parent.is_dir():
            return ()
        values: list[tuple[Path, dict[str, str]]] = []
        for directory in parent.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            marker = self._read_marker(directory)
            if marker is not None and marker.get("kind") == kind:
                values.append((directory, marker))
        return tuple(values)

    def _synchronize_references(self, directory: Path, kind: str, identifier: str, counters: _Counters) -> None:
        if not self._file_records_available:
            return
        desired = self._reference_targets(kind, identifier)
        desired_names: set[str] = set()
        for target, label, target_id in desired:
            name = self._reference_name(label, target_id, target.is_dir())
            desired_names.add(name)
            desired_names.add(name + self.REFERENCE_SUFFIX)
            destination = directory / name
            if destination.exists() or destination.is_symlink():
                continue
            if self._create_reference(destination, target):
                counters.references_created += 1
        for entry in directory.iterdir():
            if entry.name == self.MARKER_NAME or entry.name in desired_names:
                continue
            if self._is_managed_reference(entry):
                self._remove_reference(entry)

    def _reference_targets(self, kind: str, identifier: str) -> tuple[tuple[Path, str, str], ...]:
        target_refs = (
            self._service.find_case_members(InvestigationCaseId(identifier))
            if kind == "case"
            else self._service.find_collection_members(InvestigationCollectionId(identifier))
        )
        values: list[tuple[Path, str, str]] = []
        for target_ref in target_refs:
            resolved = self._resolve_target(target_ref)
            if resolved is not None:
                values.append(resolved)
        return tuple(values)

    def _resolve_target(self, target_ref: InvestigationTargetRef) -> tuple[Path, str, str] | None:
        if target_ref.target_kind == "collection":
            collection = self._service.get_collection(InvestigationCollectionId(target_ref.target_id))
            directory = self._find_container_directory("collection", target_ref.target_id)
            if collection is not None and directory is not None:
                return directory, collection.title, target_ref.target_id
            return None
        file_id = target_ref.target_id if target_ref.target_kind == "file" else None
        if target_ref.target_kind == "item":
            item = self._service.get_item(target_ref.target_id)  # type: ignore[arg-type]
            if item is not None and item.subject_kind == "file":
                file_id = item.subject_id
        if file_id is None:
            return None
        path = self._file_paths.get(file_id)
        if path is None:
            return None
        return path, path.name or file_id, file_id

    def _create_reference(self, destination: Path, target: Path) -> bool:
        try:
            os.symlink(target, destination, target_is_directory=target.is_dir())
            self._write_reference_marker(destination, target)
            return True
        except OSError:
            reference = destination.with_name(destination.name + self.REFERENCE_SUFFIX)
            try:
                self._write_json_atomic(reference, {"target": str(target), "managed_by": "CarvEx"})
                return True
            except OSError as error:
                LOGGER.warning("Impossible de créer la référence Investigation %s : %s", destination, error)
                return False

    def _remove_directory_if_safe(self, directory: Path) -> bool:
        try:
            entries = tuple(directory.iterdir())
            if any(entry.name != self.MARKER_NAME and not self._is_managed_reference(entry) for entry in entries):
                unmanaged = next(
                    entry
                    for entry in entries
                    if entry.name != self.MARKER_NAME and not self._is_managed_reference(entry)
                )
                LOGGER.warning("Dossier Investigation conservé car il contient %s", unmanaged)
                return False
            for entry in entries:
                self._remove_reference(entry)
            directory.rmdir()
            return True
        except OSError as error:
            LOGGER.warning("Impossible de supprimer le dossier Investigation %s : %s", directory, error)
            return False

    def _remove_reference(self, entry: Path) -> None:
        try:
            is_link = entry.is_symlink()
            if entry.is_dir() and not is_link:
                return
            entry.unlink(missing_ok=True)
            if is_link:
                self._reference_marker_path(entry).unlink(missing_ok=True)
        except OSError as error:
            LOGGER.warning("Impossible de supprimer la référence Investigation %s : %s", entry, error)

    def _is_managed_reference(self, entry: Path) -> bool:
        if entry.name.endswith(self.REFERENCE_SUFFIX):
            return self._read_reference_marker(entry) is not None
        if not entry.is_symlink():
            return False
        marker = self._read_reference_marker(self._reference_marker_path(entry))
        return marker is not None and marker.get("reference") == entry.name

    def _write_reference_marker(self, destination: Path, target: Path) -> None:
        self._write_json_atomic(
            self._reference_marker_path(destination),
            {"target": str(target), "reference": destination.name, "managed_by": "CarvEx"},
        )

    @classmethod
    def _reference_marker_path(cls, destination: Path) -> Path:
        return destination.with_name(destination.name + cls.REFERENCE_SUFFIX)

    @staticmethod
    def _read_reference_marker(path: Path) -> dict[str, str] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("managed_by") != "CarvEx":
            return None
        return {str(key): str(value) for key, value in payload.items() if isinstance(value, str)}

    def _write_marker(self, directory: Path, kind: str, identifier: str) -> None:
        self._write_json_atomic(directory / self.MARKER_NAME, {"kind": kind, "id": identifier, "managed_by": "CarvEx"})

    @staticmethod
    def _read_marker(directory: Path) -> dict[str, str] | None:
        try:
            payload = json.loads(
                (directory / InvestigationPhysicalRepresentationService.MARKER_NAME).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("managed_by") != "CarvEx":
            return None
        kind, identifier = payload.get("kind"), payload.get("id")
        return {"kind": kind, "id": identifier} if isinstance(kind, str) and isinstance(identifier, str) else None

    @staticmethod
    def _write_json_atomic(path: Path, payload: Mapping[str, str]) -> None:
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def _directory_name(cls, title: str, identifier: str) -> str:
        return f"{cls._safe_component(title)} [{identifier}]"

    @classmethod
    def _reference_name(cls, label: str, identifier: str, is_directory: bool) -> str:
        suffix = "" if is_directory else Path(label).suffix
        stem = Path(label).stem if suffix else label
        return f"{cls._safe_component(stem)} [{identifier}]{suffix}"

    @classmethod
    def _safe_component(cls, value: str) -> str:
        cleaned = cls._INVALID_PATH_CHARS.sub("_", value).strip().rstrip(".")
        return (cleaned or "Sans nom")[:80]

    @staticmethod
    def _title_from_directory(name: str, identifier: str) -> str | None:
        suffix = f" [{identifier}]"
        return name[: -len(suffix)] if name.endswith(suffix) else None

    def _update_title_from_directory(self, kind: str, identifier: str, title: str) -> None:
        if kind == "case":
            value = self._service.get_case(InvestigationCaseId(identifier))
            if value is not None:
                self._service.update_case(replace(value, title=title))
        else:
            value = self._service.get_collection(InvestigationCollectionId(identifier))
            if value is not None:
                self._service.update_collection(replace(value, title=title))


@dataclass(slots=True)
class _Counters:
    created: int = 0
    renamed: int = 0
    removed: int = 0
    references_created: int = 0
    warnings: list[str] = field(default_factory=list)

    def result(self) -> PhysicalSyncResult:
        return PhysicalSyncResult(
            self.created, self.renamed, self.removed, self.references_created, tuple(self.warnings)
        )
