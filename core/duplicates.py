"""Index inversé des contenus identiques déjà hashés par l'import.

Le calcul du SHA-256 appartient au pipeline d'import. Cette classe ne le
recalcule jamais : elle associe simplement chaque empreinte présente aux
``file_id`` canoniques qui la partagent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from core.file_identity import require_file_id


class DuplicateIndex:
    """Index de lecture O(1) des groupes de fichiers de contenu identique.

    Seuls les identifiants de fichier sont retenus. Les ``FileRecord`` restent
    détenus par le rapport chargé et ne sont jamais dupliqués ici.
    """

    def __init__(self) -> None:
        self._members_by_hash: dict[str, tuple[str, ...]] = {}
        self._members_by_file_id: dict[str, tuple[str, ...]] = {}

    def build(self, records: Iterable[Mapping[str, Any]]) -> None:
        """Construit l'index une fois à partir des hashes déjà disponibles."""
        grouped: dict[str, str | list[str]] = {}
        for record in records:
            fingerprint = self._normalize_hash(record.get("sha256"))
            if fingerprint is None:
                continue
            canonical_id = require_file_id(record)
            raw_id = record.get("file_id")
            file_id = raw_id if isinstance(raw_id, str) and raw_id == canonical_id else canonical_id
            previous = grouped.get(fingerprint)
            if previous is None:
                grouped[fingerprint] = file_id
            elif isinstance(previous, str):
                grouped[fingerprint] = [previous, file_id]
            else:
                previous.append(file_id)

        duplicate_members_by_hash: dict[str, tuple[str, ...]] = {}
        self._members_by_file_id = {}
        for fingerprint, member_ids in grouped.items():
            if isinstance(member_ids, str):
                continue
            members = tuple(dict.fromkeys(member_ids))
            duplicate_members_by_hash[fingerprint] = members
            for file_id in members:
                self._members_by_file_id[file_id] = members
        self._members_by_hash = duplicate_members_by_hash

    def clear(self) -> None:
        """Libère l'index lorsque le rapport courant est détaché."""
        self._members_by_hash = {}
        self._members_by_file_id = {}

    def is_duplicate(self, file_id: str) -> bool:
        return file_id in self._members_by_file_id

    def copy_count(self, file_id: str) -> int:
        """Retourne le nombre de copies, y compris le fichier lui-même."""
        members = self._members_by_file_id.get(file_id)
        return len(members) if members is not None else 1

    def members_for(self, file_id: str) -> tuple[str, ...]:
        """Retourne les membres du groupe, ou le fichier seul s'il est unique."""
        return self._members_by_file_id.get(file_id, (file_id,))

    @property
    def group_count(self) -> int:
        return len(self._members_by_hash)

    @staticmethod
    def _normalize_hash(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().casefold()
        return normalized or None


class _HasSha256(Protocol):
    sha256: str


class DuplicateDetector:
    """Compatibilité avec l'ancien script de démonstration hors interface."""

    def __init__(self) -> None:
        self.index: dict[str, list[_HasSha256]] = {}

    def add(self, recovered_file: _HasSha256) -> None:
        self.index.setdefault(recovered_file.sha256, []).append(recovered_file)

    def duplicates(self) -> dict[str, list[_HasSha256]]:
        return {sha256: files for sha256, files in self.index.items() if len(files) > 1}

    def unique(self) -> dict[str, _HasSha256]:
        return {sha256: files[0] for sha256, files in self.index.items() if len(files) == 1}


class DuplicateCounter:
    """Compte les groupes de doublons pendant l'import sans retenir les fichiers."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._group_count = 0

    def add(self, sha256: str) -> None:
        if not sha256:
            return
        previous = self._counts.get(sha256, 0)
        self._counts[sha256] = previous + 1
        if previous == 1:
            self._group_count += 1

    @property
    def group_count(self) -> int:
        return self._group_count
