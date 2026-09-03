"""Support physique abstrait ; seul ProjectRepository peut l'utiliser."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from pathlib import Path
from threading import current_thread
from typing import Any

from project.codecs import ProjectCodecRegistry
from project.locking import ProjectLock
from utils.performance import ENABLED, LOGGER, log_memory_snapshot, operation, pipeline_stage

_MISSING = object()


class ProjectStorageCorruptionError(ValueError):
    """Raised when neither the current project document nor its backup is valid."""


class ProjectStorageAdapter(ABC):
    def configure_codecs(self, registry: ProjectCodecRegistry) -> None:
        """Configure les codecs avant toute lecture d'un backend sérialisé."""
        return None

    def acquire_lock(self) -> None:
        """Acquiert éventuellement l'exclusion d'écriture du backend."""
        return None

    def close(self) -> None:
        """Libère les ressources détenues par le backend."""
        return None

    @abstractmethod
    def read(self, namespace: str, key: str, default: Any = None) -> Any: ...

    @abstractmethod
    def write(self, namespace: str, key: str, value: Any) -> None: ...

    @abstractmethod
    def delete(self, namespace: str, key: str) -> None: ...

    @abstractmethod
    def keys(self, namespace: str) -> Iterable[str]: ...

    @property
    @abstractmethod
    def is_dirty(self) -> bool: ...

    def dirty_details(self) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
        """Expose un diagnostic borné des modifications en attente.

        Les adaptateurs peuvent ne connaître que leur indicateur global. Le
        backend JSON complète ce contrat avec les namespaces et opérations
        responsables, uniquement à des fins de diagnostic.
        """
        return self.is_dirty, (), ()

    def begin_background_flush(self) -> None:
        """Réserve le backend à un flush exclusif préparé sur le thread UI."""
        return None

    def end_background_flush(self) -> None:
        """Termine la réservation créée par :meth:`begin_background_flush`."""
        return None

    @abstractmethod
    def flush(self, progress: Callable[[str], None] | None = None) -> None: ...

    @abstractmethod
    def snapshot(self) -> dict[str, dict[str, Any]]: ...


class InMemoryProjectStorage(ProjectStorageAdapter):
    """Backend de migration initial ; JSON/SQLite pourront respecter le même contrat."""

    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._dirty_namespaces: set[str] = set()

    def configure_codecs(self, registry: ProjectCodecRegistry) -> None:
        # Les objets ne sont jamais transformés dans le backend mémoire.
        return None

    def read(self, namespace: str, key: str, default: Any = None) -> Any:
        return self._namespaces.get(namespace, {}).get(key, default)

    def write(self, namespace: str, key: str, value: Any) -> None:
        values = self._namespaces.setdefault(namespace, {})
        if not self._dirty and values.get(key, _MISSING) == value:
            return
        values[key] = value
        self._dirty = True
        self._dirty_namespaces.add(namespace)

    def delete(self, namespace: str, key: str) -> None:
        values = self._namespaces.get(namespace, {})
        if key not in values:
            return
        values.pop(key)
        self._dirty = True
        self._dirty_namespaces.add(namespace)

    def keys(self, namespace: str) -> Iterable[str]:
        return tuple(self._namespaces.get(namespace, {}))

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def flush(self, progress: Callable[[str], None] | None = None) -> None:
        self._dirty = False
        self._dirty_namespaces.clear()

    def dirty_details(self) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
        return self._dirty, tuple(sorted(self._dirty_namespaces)), ()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {namespace: dict(values) for namespace, values in self._namespaces.items()}


class JsonProjectStorage(ProjectStorageAdapter):
    """Backend local JSON. Le reste de l'application ne connaît que son interface."""

    FILE_NAME = "project.json"
    BACKUP_FILE_NAME = "project.json.bak"
    CHECKSUM_FILE_NAME = "project.json.sha256"
    BACKUP_CHECKSUM_FILE_NAME = "project.json.bak.sha256"
    ENTRY_FILE_NAME = "project.carvex"
    ENTRY_FORMAT = "carvex-project-entry"
    ENTRY_VERSION = 1

    def __init__(self, root: str | Path, create: bool = False) -> None:
        self.root, explicit_entry = self._resolve_root(Path(root))
        self._project_lock = ProjectLock(self.root)
        self._file = self.root / self.FILE_NAME
        self._backup_file = self.root / self.BACKUP_FILE_NAME
        self._checksum_file = self.root / self.CHECKSUM_FILE_NAME
        self._backup_checksum_file = self.root / self.BACKUP_CHECKSUM_FILE_NAME
        self._entry_file = self.root / self.ENTRY_FILE_NAME
        self._entry_needs_write = False
        self._recovered_from_backup = False
        if create:
            self._raw_namespaces: dict[str, dict[str, Any]] = {}
            self._entry_needs_write = True
        else:
            self._raw_namespaces = self._load_document_with_recovery()
            if explicit_entry or self._entry_file.is_file():
                try:
                    self._validate_entry_file()
                except ValueError:
                    # The entry file has no business data and can safely be regenerated.
                    self._entry_needs_write = True
            else:
                self._entry_needs_write = True
        self._dirty = False
        self._dirty_namespaces: set[str] = set()
        self._dirty_operations: dict[str, str] = {}
        self._background_flush_active = False
        self._namespaces: dict[str, dict[str, Any]] | None = {} if create else None
        self._codecs: ProjectCodecRegistry | None = None

    @classmethod
    def exists(cls, root: str | Path) -> bool:
        candidate = Path(root)
        project_root = (
            candidate.parent if candidate.name == cls.ENTRY_FILE_NAME and not candidate.is_dir() else candidate
        )
        return (project_root / cls.FILE_NAME).is_file() or (project_root / cls.BACKUP_FILE_NAME).is_file()

    @classmethod
    def entry_path(cls, root: str | Path) -> Path:
        """Retourne le fichier d'entrée officiel, pour l'UI et une future association Windows."""
        project_root, _explicit_entry = cls._resolve_root(Path(root))
        return project_root / cls.ENTRY_FILE_NAME

    def read(self, namespace: str, key: str, default: Any = None) -> Any:
        return self._ensure_decoded().get(namespace, {}).get(key, default)

    def write(self, namespace: str, key: str, value: Any) -> None:
        self._ensure_writable()
        values = self._ensure_decoded().setdefault(namespace, {})
        # Une comparaison structurelle n'est nécessaire que lorsqu'elle peut
        # éviter une sérialisation complète. Une fois dirty, le flush est déjà
        # requis : ne comparons pas un index potentiellement massif une seconde
        # fois pour une écriture qui sera persistée de toute façon.
        current = values.get(key, _MISSING)
        if not self._dirty and current == value:
            return
        if ENABLED and not self._dirty and namespace == "workspaces":
            changes = _bounded_structural_diff(current, value)
            LOGGER.info(
                "[Storage] clean write differs namespace=%s key=%s changed_paths=%s",
                namespace,
                key,
                changes,
            )
        values[key] = value
        self._mark_dirty(namespace, f"write:{key}")

    def delete(self, namespace: str, key: str) -> None:
        self._ensure_writable()
        values = self._ensure_decoded().get(namespace, {})
        if key not in values:
            return
        values.pop(key)
        self._mark_dirty(namespace, f"delete:{key}")

    def keys(self, namespace: str) -> Iterable[str]:
        return tuple(self._ensure_decoded().get(namespace, {}))

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def dirty_details(self) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
        namespaces = tuple(sorted(self._dirty_namespaces))
        operations = tuple(f"{namespace}:{self._dirty_operations[namespace]}" for namespace in namespaces)
        return self._dirty, namespaces, operations

    @property
    def recovered_from_backup(self) -> bool:
        """Whether opening restored the last known valid project document."""
        return self._recovered_from_backup

    def begin_background_flush(self) -> None:
        if self._background_flush_active:
            raise RuntimeError("Une sauvegarde asynchrone du projet est déjà active.")
        self._background_flush_active = True

    def end_background_flush(self) -> None:
        self._background_flush_active = False

    def flush(self, progress: Callable[[str], None] | None = None) -> None:
        if not self._dirty and self._file.is_file():
            if ENABLED:
                LOGGER.info("[Storage] flush skipped reason=clean dirty=False dirty_namespaces=[]")
            self._ensure_entry_file()
            return
        self._notify_progress(progress, "preparing")
        if ENABLED:
            dirty, namespaces, operations = self.dirty_details()
            LOGGER.info(
                "[Storage] full flush reason=%s dirty=%s dirty_namespaces=%s dirty_operations=%s",
                "dirty" if dirty else "missing_primary",
                dirty,
                list(namespaces),
                list(operations),
            )
        self.root.mkdir(parents=True, exist_ok=True)
        document = self._ensure_decoded()
        self._validate_document(document)
        if ENABLED:
            namespace_entries = ",".join(f"{namespace}:{len(values)}" for namespace, values in sorted(document.items()))
            LOGGER.info(
                "[Sauvegarde] JsonProjectStorage.flush thread=%s namespaces=%d entries=%d entries_by_namespace=%s",
                current_thread().name,
                len(document),
                sum(len(values) for values in document.values()),
                namespace_entries,
            )
            log_memory_snapshot("JsonProjectStorage.before_encode")
        with (
            pipeline_stage("JsonProjectStorage.modèles vers primitives"),
            operation("JsonProjectStorage", "encode_models"),
        ):
            self._notify_progress(progress, "encoding_models")
            encoded = _encode(document, self._require_codecs())
        log_memory_snapshot("JsonProjectStorage.after_encode")
        with pipeline_stage("JsonProjectStorage.encodage JSON"), operation("JsonProjectStorage", "json_dumps"):
            self._notify_progress(progress, "serializing_json")
            payload = json.dumps(encoded, ensure_ascii=False, indent=2).encode("utf-8")
        if ENABLED:
            LOGGER.info("[Sauvegarde] JSON produit bytes=%d", len(payload))
            log_memory_snapshot("JsonProjectStorage.after_json_dumps")
        with pipeline_stage("JsonProjectStorage.validation"):
            self._notify_progress(progress, "validating")
            # json.dumps vient de produire ``payload`` à partir du document déjà
            # validé. Le reparser intégralement ne renforce pas sa validité.
            self._validate_document(document)
        with pipeline_stage("JsonProjectStorage.préimage disque"):
            previous_primary = self._read_file(self._file)
            previous_checksum = self._read_file(self._checksum_file)
            previous_entry = self._read_file(self._entry_file)
        entry_needs_write = self._entry_needs_write
        try:
            if previous_primary is not None:
                with pipeline_stage("JsonProjectStorage.backup"):
                    self._notify_progress(progress, "backup")
                    self._create_backup()
            with pipeline_stage("JsonProjectStorage.écriture atomique projet"):
                self._notify_progress(progress, "atomic_write")
                self._atomic_write(self._file, payload)
            with pipeline_stage("JsonProjectStorage.checksum"):
                self._notify_progress(progress, "checksum")
                self._atomic_write(self._checksum_file, f"{self._checksum(payload)}\n".encode("ascii"))
            with pipeline_stage("JsonProjectStorage.fichier entrée"):
                self._notify_progress(progress, "finalizing")
                self._ensure_entry_file()
        except Exception:
            self._restore_file(self._file, previous_primary)
            self._restore_file(self._checksum_file, previous_checksum)
            self._restore_file(self._entry_file, previous_entry)
            self._entry_needs_write = entry_needs_write
            raise
        self._dirty = False
        self._dirty_namespaces.clear()
        self._dirty_operations.clear()
        log_memory_snapshot("JsonProjectStorage.after_flush")

    @staticmethod
    def _notify_progress(progress: Callable[[str], None] | None, phase: str) -> None:
        if progress is not None:
            progress(phase)

    def _ensure_writable(self) -> None:
        if self._background_flush_active:
            raise RuntimeError("Le projet est en cours de sauvegarde ; les écritures sont temporairement suspendues.")

    def _mark_dirty(self, namespace: str, operation: str) -> None:
        was_dirty = self._dirty
        self._dirty = True
        self._dirty_namespaces.add(namespace)
        self._dirty_operations[namespace] = operation
        if ENABLED and not was_dirty:
            LOGGER.info(
                "[Storage] dirty transition clean_to_dirty namespace=%s operation=%s",
                namespace,
                operation,
            )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {namespace: dict(values) for namespace, values in self._ensure_decoded().items()}

    def configure_codecs(self, registry: ProjectCodecRegistry) -> None:
        if self._codecs is not None and self._codecs is not registry:
            raise RuntimeError("Les codecs d'un projet JSON ne peuvent pas être remplacés.")
        self._codecs = registry

    def acquire_lock(self) -> None:
        self._project_lock.acquire()
        try:
            self._ensure_entry_file()
        except Exception:
            self._project_lock.release()
            raise

    def close(self) -> None:
        self._project_lock.release()

    def _ensure_entry_file(self) -> None:
        if not self._entry_needs_write:
            return
        self._write_entry_file()
        self._entry_needs_write = False

    def _load_document_with_recovery(self) -> dict[str, Any]:
        primary, primary_error = self._read_valid_document(self._file, self._checksum_file)
        if primary is not None:
            return primary
        backup, backup_error = self._read_valid_document(self._backup_file, self._backup_checksum_file)
        if backup is None:
            if primary_error == "absent" and backup_error == "absent":
                raise FileNotFoundError(f"Projet introuvable : {self.root}")
            raise ProjectStorageCorruptionError(
                f"Projet corrompu : {self._file} ({primary_error}); sauvegarde indisponible ({backup_error})."
            )
        self._restore_backup()
        self._recovered_from_backup = True
        return backup

    @classmethod
    def _read_valid_document(cls, document: Path, checksum_file: Path) -> tuple[dict[str, Any] | None, str]:
        if not document.is_file():
            return None, "absent"
        try:
            payload = document.read_bytes()
            if checksum_file.is_file():
                expected = checksum_file.read_text(encoding="ascii").strip().lower()
                if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                    return None, "checksum invalide"
                if expected != cls._checksum(payload):
                    return None, "checksum non concordant"
            decoded = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            return None, type(error).__name__
        if not isinstance(decoded, dict):
            return None, "racine JSON invalide"
        return decoded, ""

    def _create_backup(self) -> None:
        payload = self._file.read_bytes()
        previous_backup = self._read_file(self._backup_file)
        previous_checksum = self._read_file(self._backup_checksum_file)
        try:
            self._atomic_write(self._backup_file, payload)
            self._atomic_write(self._backup_checksum_file, f"{self._checksum(payload)}\n".encode("ascii"))
        except Exception:
            self._restore_file(self._backup_file, previous_backup)
            self._restore_file(self._backup_checksum_file, previous_checksum)
            raise

    def _restore_backup(self) -> None:
        payload = self._backup_file.read_bytes()
        self._atomic_write(self._file, payload)
        self._atomic_write(self._checksum_file, f"{self._checksum(payload)}\n".encode("ascii"))

    @staticmethod
    def _read_file(target: Path) -> bytes | None:
        return target.read_bytes() if target.is_file() else None

    @classmethod
    def _restore_file(cls, target: Path, payload: bytes | None) -> None:
        if payload is None:
            target.unlink(missing_ok=True)
        else:
            cls._atomic_write(target, payload)

    @staticmethod
    def _checksum(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _validate_payload(payload: bytes) -> None:
        decoded = json.loads(payload.decode("utf-8"))
        JsonProjectStorage._validate_document(decoded)

    @staticmethod
    def _validate_document(document: object) -> None:
        """Vérifie l'invariant de racine avant sérialisation, sans reparse coûteux."""
        if not isinstance(document, dict):
            raise ValueError("Le contenu d'un projet JSON doit etre un mapping.")

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _ensure_decoded(self) -> dict[str, dict[str, Any]]:
        if self._namespaces is None:
            decoded = _decode(self._raw_namespaces, self._require_codecs())
            if not isinstance(decoded, dict):
                raise ValueError("Le contenu d'un projet JSON doit être un mapping.")
            self._namespaces = decoded
        return self._namespaces

    def _require_codecs(self) -> ProjectCodecRegistry:
        if self._codecs is None:
            raise RuntimeError("Les codecs doivent être configurés avant d'accéder au projet JSON.")
        return self._codecs

    @classmethod
    def _resolve_root(cls, candidate: Path) -> tuple[Path, bool]:
        if candidate.is_dir():
            return candidate, False
        if candidate.name == cls.ENTRY_FILE_NAME:
            return candidate.parent, True
        return candidate, False

    def _write_entry_file(self) -> None:
        """Écrit un point d'entrée évolutif sans coupler les stores au format physique."""
        payload = {
            "format": self.ENTRY_FORMAT,
            "entry_version": self.ENTRY_VERSION,
            "storage": self.FILE_NAME,
        }
        self._atomic_write(self._entry_file, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))

    def _validate_entry_file(self) -> None:
        try:
            payload = json.loads(self._entry_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Fichier projet invalide : {self._entry_file}") from error
        if (
            not isinstance(payload, dict)
            or payload.get("format") != self.ENTRY_FORMAT
            or payload.get("entry_version") != self.ENTRY_VERSION
            or payload.get("storage") != self.FILE_NAME
        ):
            raise ValueError(f"Fichier projet incompatible : {self._entry_file}")


def _bounded_structural_diff(previous: object, current: object, *, limit: int = 24) -> list[str]:
    """Décrit un écart de persistance sans journaliser une charge complète.

    Ce diagnostic ne sert qu'à expliquer une transition clean → dirty. Les
    champs binaires et les collections potentiellement massives sont donc
    réduits à leur chemin et à une représentation courte de leur valeur.
    """
    changes: list[str] = []

    def visit(path: str, left: object, right: object) -> None:
        if len(changes) >= limit or left == right:
            return
        if is_dataclass(left) and is_dataclass(right) and type(left) is type(right):
            for item in fields(left):
                visit(f"{path}.{item.name}" if path else item.name, getattr(left, item.name), getattr(right, item.name))
            return
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left) | set(right), key=str):
                key_path = f"{path}.{key}" if path else str(key)
                visit(key_path, left.get(key, _MISSING), right.get(key, _MISSING))
                if len(changes) >= limit:
                    return
            return
        if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)) and len(left) == len(right):
            for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
                visit(f"{path}[{index}]", left_item, right_item)
                if len(changes) >= limit:
                    return
            return
        changes.append(f"{path}: {_short_value(left)} -> {_short_value(right)}")

    visit("", previous, current)
    if len(changes) == limit:
        changes.append("…")
    return changes


def _short_value(value: object, *, maximum: int = 96) -> str:
    if value is _MISSING:
        return "<absent>"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Mapping):
        return f"<{type(value).__name__}:{len(value)}>"
    if isinstance(value, (tuple, list, frozenset, set)):
        return f"<{type(value).__name__}:{len(value)}>"
    text = repr(value)
    return text if len(text) <= maximum else f"{text[:maximum - 1]}…"


def _encode(value: Any, codecs: ProjectCodecRegistry) -> Any:
    if isinstance(value, datetime):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"__type__": "bytes", "value": value.hex()}
    registered = codecs.serialize(value)
    if registered is not None:
        type_id, payload = registered
        return {"__type__": type_id, "value": _encode(payload, codecs)}
    if is_dataclass(value):
        raise ValueError(f"Aucun codec enregistré pour {type(value).__module__}.{type(value).__name__}")
    # The model exposes immutable mapping proxies; storage remains agnostic.
    if isinstance(value, Mapping):
        return {
            "__type__": "dict",
            "value": [[_encode(key, codecs), _encode(item, codecs)] for key, item in value.items()],
        }
    if isinstance(value, (tuple, list, frozenset, set)):
        return {"__type__": type(value).__name__, "value": [_encode(item, codecs) for item in value]}
    return value


def _decode(value: Any, codecs: ProjectCodecRegistry) -> Any:
    if isinstance(value, list):
        return [_decode(item, codecs) for item in value]
    if not isinstance(value, dict) or "__type__" not in value:
        return value
    kind, payload = value["__type__"], value.get("value")
    if kind == "datetime":
        return datetime.fromisoformat(payload)
    if kind == "bytes":
        return bytes.fromhex(payload)
    if kind == "dict":
        return {_decode(key, codecs): _decode(item, codecs) for key, item in payload}
    if kind in {"tuple", "list", "frozenset", "set"}:
        items = [_decode(item, codecs) for item in payload]
        return {"tuple": tuple, "list": list, "frozenset": frozenset, "set": set}[kind](items)
    if isinstance(kind, str):
        return codecs.deserialize(kind, _decode(payload, codecs))
    return value
