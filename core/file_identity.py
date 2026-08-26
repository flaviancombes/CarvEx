"""Identité canonique et sûre des preuves fichier importées.

Un ``file_id`` ne doit jamais dépendre de l'ordre d'un rapport.  La version
actuelle dérive donc l'identité d'une empreinte de contenu obligatoire et de
la provenance textuelle fournie par le rapport.  Une preuve modifiée ou dont
la provenance change devient une *nouvelle* preuve ; les références existantes
ne peuvent alors pas être silencieusement redirigées.
"""

from __future__ import annotations

import posixpath
import unicodedata
from collections.abc import MutableMapping, Sequence
from typing import Any
from uuid import UUID, uuid4, uuid5

FILE_ID_FIELD = "file_id"
FILE_IDENTITY_SCHEME = "content-provenance-v1"
_FILE_ID_NAMESPACE = UUID("2c5d5296-1b56-4da0-ae17-a4b81f8d9eaf")


class FileIdentityError(ValueError):
    """Une donnée de fichier ne respecte pas le contrat d'identité."""


class LegacyFileIdentityError(FileIdentityError):
    """Un projet positionnel ne peut pas être remappé de manière sûre."""


def assert_project_identity_compatible(scheme: str | None, legacy_namespace: str | None) -> None:
    """Refuse explicitement les projets dont les références sont positionnelles.

    Les anciens ``file_id`` ne peuvent pas être traduits sans connaître le
    rapport exact et toutes les associations historiques. Réattribuer des
    identifiants serait une corruption silencieuse ; il n'existe donc pas de
    migration automatique.
    """
    if scheme not in {None, FILE_IDENTITY_SCHEME}:
        raise LegacyFileIdentityError(
            "Le projet utilise un schéma d'identité de preuve inconnu ; le rapport n'est pas chargé."
        )
    if scheme is None and legacy_namespace is not None:
        raise LegacyFileIdentityError(
            "Ce projet utilise des identités de fichiers basées sur la position du rapport. "
            "Aucune migration sûre n'est possible : créez un nouveau projet puis réassociez explicitement les preuves."
        )


def new_import_namespace() -> str:
    """Compatibilité historique : les nouvelles identités n'ont plus de namespace projet."""
    return str(uuid4())


def normalize_namespace(value: str) -> str:
    """Compatibilité de lecture des métadonnées de projets historiques."""
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise FileIdentityError("L'espace de noms d'identité des fichiers est invalide.") from error


def file_identity_material(record: MutableMapping[str, Any] | dict[str, Any]) -> str:
    """Retourne le matériau stable, complet et non ambigu d'une preuve.

    Le SHA-256 distingue tout changement de contenu. ``source_path`` distingue
    deux occurrences distinctes d'un même contenu sans faire appel à l'ordre,
    au nom affiché ou au chemin d'export. Les valeurs incomplètes sont refusées
    plutôt que complétées par une approximation dangereuse.
    """
    try:
        digest = str(record["sha256"]).strip().lower()
        source_path = _normalize_source_path(record["source_path"])
    except (KeyError, TypeError) as error:
        raise FileIdentityError("Chaque preuve importée doit fournir sha256 et source_path.") from error
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise FileIdentityError("Le SHA-256 d'une preuve importée doit contenir 64 caractères hexadécimaux.")
    return f"{FILE_IDENTITY_SCHEME}\x00{digest}\x00{source_path}"


def file_id_for_record(record: MutableMapping[str, Any] | dict[str, Any]) -> str:
    """Retourne l'UUID déterministe d'une preuve sans dépendre de sa position."""
    return str(uuid5(_FILE_ID_NAMESPACE, file_identity_material(record)))


def assign_file_ids(records: Sequence[MutableMapping[str, Any]]) -> tuple[str, ...]:
    """Attribue l'identité canonique et détecte toute collision logique.

    Deux entrées ayant le même contenu et la même provenance ne peuvent pas
    être distinguées sans introduire un index de rapport. Le rapport est donc
    rejeté explicitement, ce qui est préférable à un rattachement ambigu.
    """
    identifiers: list[str] = []
    seen: set[str] = set()
    for record in records:
        identifier = file_id_for_record(record)
        if identifier in seen:
            raise FileIdentityError("Le rapport contient deux preuves avec la même identité canonique.")
        record[FILE_ID_FIELD] = identifier
        identifiers.append(identifier)
        seen.add(identifier)
    return tuple(identifiers)


def require_file_id(file_record: MutableMapping[str, Any] | dict[str, Any] | Any) -> str:
    """Lit l'identité obligatoire sans aucun chemin de repli ambigu."""
    try:
        value = file_record[FILE_ID_FIELD]
    except (KeyError, TypeError) as error:
        raise FileIdentityError("Un fichier importé doit posséder un file_id.") from error
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise FileIdentityError("Le file_id d'un fichier importé est invalide.") from error


def _normalize_source_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FileIdentityError("La provenance source_path d'une preuve importée est requise.")
    normalized = unicodedata.normalize("NFC", value.strip().replace("\\", "/"))
    prefix = "//" if normalized.startswith("//") else ""
    normalized = posixpath.normpath(normalized)
    return prefix + normalized if prefix and not normalized.startswith("//") else normalized
