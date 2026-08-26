"""Registre extensible des codecs de persistance du projet.

Le stockage ne connaît aucun type métier. Les modules enregistrent leurs
propres codecs dans ce registre avant la première lecture d'un projet.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProjectCodec(Generic[T]):
    """Conversion d'un type métier identifié vers une charge sérialisable."""

    type_id: str
    value_type: type[T]
    encode: Callable[[T], Any]
    decode: Callable[[Any], T]


class ProjectCodecRegistry:
    """Association bidirectionnelle entre les types Python et leurs codecs."""

    def __init__(self) -> None:
        self._by_type: dict[type[object], ProjectCodec[object]] = {}
        self._by_type_id: dict[str, ProjectCodec[object]] = {}

    def register(self, codec: ProjectCodec[T]) -> None:
        if not codec.type_id:
            raise ValueError("L'identifiant d'un codec est requis.")
        existing_by_type = self._by_type.get(codec.value_type)
        existing_by_id = self._by_type_id.get(codec.type_id)
        if existing_by_type is not None and existing_by_type != codec:
            raise ValueError(f"Codec déjà enregistré pour {codec.value_type.__name__}.")
        if existing_by_id is not None and existing_by_id != codec:
            raise ValueError(f"Identifiant de codec déjà enregistré : {codec.type_id}")
        self._by_type[codec.value_type] = codec  # type: ignore[assignment]
        self._by_type_id[codec.type_id] = codec  # type: ignore[assignment]

    def register_many(self, codecs: Iterable[ProjectCodec[object]]) -> None:
        for codec in codecs:
            self.register(codec)

    def resolve_for_value(self, value: object) -> ProjectCodec[object] | None:
        return self._by_type.get(type(value))

    def resolve(self, type_id: str) -> ProjectCodec[object]:
        try:
            return self._by_type_id[type_id]
        except KeyError as exc:
            raise ValueError(f"Codec de projet inconnu : {type_id}") from exc

    def serialize(self, value: object) -> tuple[str, object] | None:
        codec = self.resolve_for_value(value)
        return None if codec is None else (codec.type_id, codec.encode(value))

    def deserialize(self, type_id: str, payload: object) -> object:
        return self.resolve(type_id).decode(payload)


def dataclass_codec(type_id: str, value_type: type[T]) -> ProjectCodec[T]:
    """Codec réutilisable pour une dataclass dont les champs sont publics."""

    return ProjectCodec(
        type_id=type_id,
        value_type=value_type,
        encode=lambda value: {item.name: getattr(value, item.name) for item in fields(value)},
        decode=lambda payload: value_type(**_mapping_payload(payload)),
    )


def enum_codec(type_id: str, value_type: type[T]) -> ProjectCodec[T]:
    """Codec réutilisable pour un Enum métier."""

    if not issubclass(value_type, Enum):
        raise TypeError("enum_codec requiert un type Enum.")
    return ProjectCodec(
        type_id=type_id,
        value_type=value_type,
        encode=lambda value: value.value,  # type: ignore[union-attr]
        decode=lambda payload: value_type(payload),
    )


def _mapping_payload(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("La charge d'un codec dataclass doit être un mapping.")
    return payload


def create_core_codec_registry() -> ProjectCodecRegistry:
    """Crée les codecs du noyau, sans importer de module métier optionnel."""

    from project.models import (
        ProjectManifest,
        ProjectMetadata,
        ProjectSettings,
        ProjectState,
        ReportSourceAuditEntry,
        ReportSourceSnapshot,
        Workspace,
    )

    registry = ProjectCodecRegistry()
    registry.register_many(
        [
            dataclass_codec("dataclass:project.models.ProjectManifest", ProjectManifest),
            dataclass_codec("dataclass:project.models.ProjectMetadata", ProjectMetadata),
            dataclass_codec("dataclass:project.models.ReportSourceAuditEntry", ReportSourceAuditEntry),
            dataclass_codec("dataclass:project.models.ReportSourceSnapshot", ReportSourceSnapshot),
            dataclass_codec("dataclass:project.models.ProjectSettings", ProjectSettings),
            dataclass_codec("dataclass:project.models.ProjectState", ProjectState),
            dataclass_codec("dataclass:project.models.Workspace", Workspace),
        ]
    )
    return registry
