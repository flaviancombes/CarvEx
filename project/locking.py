"""Verrou exclusif, local et récupérable des projets CarvEx."""

from __future__ import annotations

import ctypes
import json
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class ProjectLockedError(RuntimeError):
    """Le projet est déjà détenu par une autre instance CarvEx."""


@dataclass(frozen=True, slots=True)
class ProjectLockOwner:
    hostname: str
    pid: int
    acquired_at: str
    token: str


class ProjectLock:
    """Détient un verrou exclusif par dossier, sans synchronisation distribuée.

    ``mkdir`` est atomique sur les systèmes pris en charge. En cas de crash,
    le dossier persiste mais son propriétaire local mort est détecté avant une
    récupération. Un verrou d'un autre hôte ou sans métadonnées valides n'est
    jamais supprimé automatiquement : le refus est plus sûr qu'un vol de lock.
    """

    DIRECTORY_NAME = ".carvex.lock"
    OWNER_FILE_NAME = "owner.json"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._directory = project_root / self.DIRECTORY_NAME
        self._token: str | None = None

    @property
    def is_held(self) -> bool:
        return self._token is not None

    def acquire(self) -> None:
        if self.is_held:
            return
        self._project_root.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._directory.mkdir()
            except FileExistsError:
                owner = self._read_owner()
                if owner is not None and owner.hostname == socket.gethostname() and not _is_process_alive(owner.pid):
                    self._reclaim_abandoned_lock(owner)
                    continue
                raise ProjectLockedError(self._locked_message(owner)) from None
            token = str(uuid4())
            owner = ProjectLockOwner(socket.gethostname(), os.getpid(), datetime.now(UTC).isoformat(), token)
            try:
                self._write_owner(owner)
            except OSError:
                self._directory.rmdir()
                raise
            self._token = token
            return

    def release(self) -> None:
        if not self.is_held:
            return
        owner = self._read_owner()
        if owner is None or owner.token != self._token:
            raise ProjectLockedError("Le verrou du projet a été modifié pendant son ouverture.")
        try:
            (self._directory / self.OWNER_FILE_NAME).unlink()
            self._directory.rmdir()
        finally:
            self._token = None

    def _reclaim_abandoned_lock(self, owner: ProjectLockOwner) -> None:
        stale = self._directory.with_name(f"{self.DIRECTORY_NAME}.stale-{uuid4()}")
        try:
            self._directory.replace(stale)
        except FileNotFoundError:
            return
        try:
            (stale / self.OWNER_FILE_NAME).unlink(missing_ok=True)
            stale.rmdir()
        except OSError as error:
            raise ProjectLockedError(
                f"Le verrou abandonné du projet ({owner.hostname}, PID {owner.pid}) ne peut pas être récupéré : {error}"
            ) from error

    def _read_owner(self) -> ProjectLockOwner | None:
        try:
            payload = json.loads((self._directory / self.OWNER_FILE_NAME).read_text(encoding="utf-8"))
            return ProjectLockOwner(
                hostname=str(payload["hostname"]),
                pid=int(payload["pid"]),
                acquired_at=str(payload["acquired_at"]),
                token=str(payload["token"]),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_owner(self, owner: ProjectLockOwner) -> None:
        path = self._directory / self.OWNER_FILE_NAME
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "hostname": owner.hostname,
                    "pid": owner.pid,
                    "acquired_at": owner.acquired_at,
                    "token": owner.token,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _locked_message(owner: ProjectLockOwner | None) -> str:
        if owner is None:
            return "Le projet est verrouillé avec des métadonnées invalides ; récupération manuelle requise."
        return (
            f"Le projet est déjà ouvert sur {owner.hostname} (PID {owner.pid}, verrou acquis le {owner.acquired_at})."
        )


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a harmless existence probe on Windows:
        # unlike POSIX, it can terminate the target process.  Query the
        # process status through Kernel32 instead.
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Access can be denied for a live process owned by another user;
            # refusing recovery is safer than stealing its lock.
            return ctypes.get_last_error() == 5
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
