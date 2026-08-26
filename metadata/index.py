"""Index persistant et reconstructible des champs de métadonnées."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from numbers import Number
from types import MappingProxyType
from typing import Protocol

from metadata.base import MetadataField, MetadataValueType
from utils.performance import pipeline_stage


class _Predicate(Protocol):
    identifier: str
    value: object | None
    present: bool


class MetadataIndex:
    """Index inversés de lecture, sans extraction ni référence au disque.

    Les valeurs restent détenues par :class:`MetadataStore`. L'index conserve
    uniquement les clés nécessaires aux prédicats, à la recherche et au tri.
    """

    SNAPSHOT_VERSION = 2

    def __init__(self, snapshot: Mapping[str, object] | None = None) -> None:
        snapshot = snapshot or {}
        self._by_category = self._decode_sets(snapshot.get("category"))
        self._by_source = self._decode_sets(snapshot.get("source"))
        self._by_value = self._decode_sets(snapshot.get("value"))
        self._by_identifier = self._decode_sets(snapshot.get("identifier"))
        self._by_field_value = self._decode_sets(snapshot.get("field_value"))
        self._identifiers_by_category = self._decode_sets(snapshot.get("identifiers_by_category"))
        self._sort_values = self._decode_values(snapshot.get("sort_value"))
        self._sort_types = self._decode_values(snapshot.get("sort_type"))
        self._file_ids = (
            {str(value) for value in snapshot.get("file_ids", ())}
            if isinstance(snapshot.get("file_ids", ()), (list, tuple))
            else set()
        )
        self._has_structured_fields = "identifier" in snapshot and "field_value" in snapshot
        # This process-local cache records the fields used for new additions.
        # Persisted updates supply their previous fields through ``replace``;
        # keeping this cache out of the snapshot avoids duplicating primary
        # metadata in the index document.
        self._fields_by_file: dict[str, tuple[MetadataField, ...]] = {}

    @property
    def has_structured_fields(self) -> bool:
        """Whether this snapshot supports field-level predicates and typed sort."""
        return self._has_structured_fields

    @property
    def file_ids(self) -> frozenset[str]:
        return frozenset(self._file_ids)

    def add(self, file_id: str, fields: Iterable[MetadataField]) -> None:
        values = tuple(fields)
        previous = self._fields_by_file.get(file_id, ())
        if file_id in self._file_ids:
            self._remove_fields(file_id, previous)
        self._add_fields(file_id, values)
        self._fields_by_file[file_id] = values

    def replace(
        self,
        file_id: str,
        previous_fields: Iterable[MetadataField],
        fields: Iterable[MetadataField],
    ) -> None:
        """Replace one file contribution without scanning unrelated index keys."""
        previous = tuple(previous_fields)
        values = tuple(fields)
        if file_id in self._file_ids:
            with pipeline_stage("MetadataIndex.remove_fields"):
                self._remove_fields(file_id, previous)
        with pipeline_stage("MetadataIndex.add_fields"):
            self._add_fields(file_id, values)
        self._fields_by_file[file_id] = values

    def _add_fields(self, file_id: str, fields: tuple[MetadataField, ...]) -> None:
        self._file_ids.add(file_id)
        for field in fields:
            identifier = field.identifier.casefold()
            self._by_category.setdefault(field.category.value, set()).add(file_id)
            self._by_source.setdefault(field.source.casefold(), set()).add(file_id)
            self._by_identifier.setdefault(identifier, set()).add(file_id)
            self._identifiers_by_category.setdefault(field.category.value, set()).add(identifier)
            self._sort_values.setdefault(identifier, {})[file_id] = field.value
            self._sort_types.setdefault(identifier, {})[file_id] = field.value_type.value
            self._by_field_value.setdefault(self._field_value_key(identifier, field.value), set()).add(file_id)
            for token in self._tokens(field):
                self._by_value.setdefault(token, set()).add(file_id)
        self._has_structured_fields = True

    def remove(self, file_id: str, fields: Iterable[MetadataField] | None = None) -> None:
        """Remove one known contribution in O(k), where k is its field count."""
        values = tuple(fields) if fields is not None else self._fields_by_file.get(file_id)
        if values is None:
            raise ValueError("Les champs précédents sont requis pour supprimer cette entrée d'index.")
        self._remove_fields(file_id, values)
        self._fields_by_file.pop(file_id, None)

    def _remove_fields(self, file_id: str, fields: tuple[MetadataField, ...]) -> None:
        self._file_ids.discard(file_id)
        for field in fields:
            identifier = field.identifier.casefold()
            category = field.category.value
            self._discard(self._by_category, category, file_id)
            self._discard(self._by_source, field.source.casefold(), file_id)
            self._discard(self._by_field_value, self._field_value_key(identifier, field.value), file_id)
            for token in self._tokens(field):
                self._discard(self._by_value, token, file_id)
            values = self._sort_values.get(identifier)
            if values is not None:
                values.pop(file_id, None)
                self._sort_types[identifier].pop(file_id, None)
                if not values:
                    del self._sort_values[identifier]
                    del self._sort_types[identifier]
            self._discard(self._by_identifier, identifier, file_id)
            identifiers = self._identifiers_by_category.get(category)
            if identifiers is not None and identifier not in self._by_identifier:
                identifiers.discard(identifier)
                if not identifiers:
                    del self._identifiers_by_category[category]

    @staticmethod
    def _discard(mapping: dict[str, set[str]], key: str, file_id: str) -> None:
        values = mapping.get(key)
        if values is None:
            return
        values.discard(file_id)
        if not values:
            del mapping[key]

    def search(self, text: str) -> frozenset[str]:
        tokens = tuple(token for token in text.casefold().split() if token)
        if not tokens:
            return frozenset()
        matches = [self._by_value.get(token, set()) for token in tokens]
        return frozenset(set.intersection(*matches)) if matches else frozenset()

    def by_category(self, category: str) -> frozenset[str]:
        return frozenset(self._by_category.get(category.casefold(), ()))

    def by_source(self, source: str) -> frozenset[str]:
        return frozenset(self._by_source.get(source.casefold(), ()))

    def identifiers(self) -> tuple[str, ...]:
        """Stable field identifiers currently present in the persistent index."""
        return tuple(sorted(self._by_identifier))

    def identifiers_by_category(self, category: str) -> tuple[str, ...]:
        return tuple(sorted(self._identifiers_by_category.get(category.casefold(), ())))

    def has_field(self, identifier: str) -> frozenset[str]:
        return frozenset(self._by_identifier.get(identifier.casefold(), ()))

    def values_for(self, identifier: str) -> Mapping[str, object]:
        """Valeurs persistées d'un champ, sans Store ni lecture de fichier.

        La vue est en lecture seule : elle évite une copie transitoire de grande
        taille pendant les analyses sur plusieurs centaines de milliers de
        fichiers.
        """
        return MappingProxyType(self._sort_values.get(identifier.casefold(), {}))

    def missing_field(self, identifier: str, candidates: Iterable[str] | None = None) -> frozenset[str]:
        universe = self._file_ids if candidates is None else {str(value) for value in candidates}
        return frozenset(universe.difference(self._by_identifier.get(identifier.casefold(), ())))

    def equals(self, identifier: str, value: object) -> frozenset[str]:
        return frozenset(self._by_field_value.get(self._field_value_key(identifier.casefold(), value), ()))

    def query(self, predicates: Sequence[_Predicate], candidates: Iterable[str] | None = None) -> frozenset[str]:
        """Intersect simple immutable predicates without accessing the store or disk.

        Predicates intentionally use a tiny structural protocol to keep the
        index independent from the optional public query façade.
        """
        universe = self._file_ids if candidates is None else {str(value) for value in candidates}
        result = set(universe)
        for predicate in predicates:
            identifier = predicate.identifier.casefold()
            present = predicate.present
            value = predicate.value
            if value is None:
                matches = self._by_identifier.get(identifier, set())
            else:
                matches = self._by_field_value.get(self._field_value_key(identifier, value), set())
            result.intersection_update(matches if present else universe.difference(matches))
            if not result:
                break
        return frozenset(result)

    def sort_key(self, file_id: str, identifier: str) -> tuple[int, object, object]:
        """Typed, deterministic sort key; missing values sort after present ones."""
        normalized_identifier = identifier.casefold()
        value = self._sort_values.get(normalized_identifier, {}).get(file_id)
        value_type = self._sort_types.get(normalized_identifier, {}).get(file_id)
        return (1, "", "") if value is None else (0, *self._sortable_value(value, value_type))

    def snapshot(self) -> dict[str, object]:
        if not self._has_structured_fields:
            # Compatibility with an untouched legacy project/index.
            return {
                "category": self._encode_sets(self._by_category),
                "source": self._encode_sets(self._by_source),
                "value": self._encode_sets(self._by_value),
            }
        return {
            "version": self.SNAPSHOT_VERSION,
            "category": self._encode_sets(self._by_category),
            "source": self._encode_sets(self._by_source),
            "value": self._encode_sets(self._by_value),
            "identifier": self._encode_sets(self._by_identifier),
            "field_value": self._encode_sets(self._by_field_value),
            "identifiers_by_category": self._encode_sets(self._identifiers_by_category),
            "sort_value": {identifier: dict(values) for identifier, values in self._sort_values.items()},
            "sort_type": {identifier: dict(values) for identifier, values in self._sort_types.items()},
            "file_ids": tuple(sorted(self._file_ids)),
        }

    @staticmethod
    def _tokens(field: MetadataField) -> frozenset[str]:
        text = f"{field.identifier} {field.display_name} {field.display_value} {field.source}".casefold()
        return frozenset(re.findall(r"[\w]+", text))

    @staticmethod
    def _field_value_key(identifier: str, value: object) -> str:
        return f"{identifier}\x1f{MetadataIndex._normalized_value(value)}"

    @staticmethod
    def _normalized_value(value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).casefold().strip()

    @staticmethod
    def _sortable_value(value: object, raw_value_type: object) -> tuple[int, object]:
        try:
            value_type = MetadataValueType(str(raw_value_type))
        except ValueError:
            value_type = MetadataValueType.TEXT
        if value_type is MetadataValueType.DATETIME:
            if isinstance(value, datetime):
                return (0, value.timestamp())
            try:
                return (0, datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
            except ValueError:
                return (1, str(value).casefold())
        if value_type in {MetadataValueType.INTEGER, MetadataValueType.DECIMAL}:
            try:
                return (0, float(value))
            except (TypeError, ValueError):
                return (1, str(value).casefold())
        if value_type is MetadataValueType.BOOLEAN:
            return (0, int(bool(value)))
        if isinstance(value, Number):
            return (0, float(value))
        return (1, str(value).casefold())

    @staticmethod
    def _decode_sets(raw: object) -> dict[str, set[str]]:
        if not isinstance(raw, Mapping):
            return {}
        return {
            str(key): {str(value) for value in values}
            for key, values in raw.items()
            if isinstance(values, (list, tuple))
        }

    @staticmethod
    def _decode_values(raw: object) -> dict[str, dict[str, object]]:
        if not isinstance(raw, Mapping):
            return {}
        return {
            str(identifier): {str(file_id): value for file_id, value in values.items()}
            for identifier, values in raw.items()
            if isinstance(values, Mapping)
        }

    @staticmethod
    def _encode_sets(values: Mapping[str, set[str]]) -> dict[str, tuple[str, ...]]:
        return {key: tuple(sorted(file_ids)) for key, file_ids in values.items()}
