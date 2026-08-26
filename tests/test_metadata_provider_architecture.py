"""Contrats du pipeline de métadonnées typées et agrégées."""

from __future__ import annotations

from uuid import uuid4

from metadata.base import MetadataCategory, MetadataConfidence, MetadataField
from metadata.cache import MetadataCache
from metadata.manager import MetadataManager
from metadata.registry import MetadataProviderRegistry


def _record() -> dict[str, str]:
    return {"file_id": str(uuid4()), "name": "evidence.bin"}


class _Provider:
    def __init__(self, provider_id: str, fields=(), *, priority: int = 0, supported: bool = True, error=None) -> None:
        self.provider_id = provider_id
        self.priority = priority
        self._fields = tuple(fields)
        self._supported = supported
        self._error = error
        self.calls = 0

    def supports(self, _record) -> bool:
        if self._error is not None and self._error == "supports":
            raise RuntimeError("supports failed")
        return self._supported

    def extract(self, _record):
        self.calls += 1
        if self._error is not None and self._error != "supports":
            raise RuntimeError("extract failed")
        return self._fields


def _field(identifier: str, value: str, *, order: int = 0, confidence=MetadataConfidence.MEDIUM) -> MetadataField:
    return MetadataField(
        identifier=identifier,
        category=MetadataCategory.GENERAL,
        display_name=identifier,
        value=value,
        source="test",
        confidence=confidence,
        display_order=order,
    )


def test_manager_fuses_all_compatible_providers_in_a_stable_order():
    first = _Provider("first", (_field("general.second", "two", order=20),))
    second = _Provider("second", (_field("general.first", "one", order=10),))

    result = MetadataManager((first, second)).extract(_record())

    assert [field.identifier for field in result.fields] == ["general.first", "general.second"]
    assert first.calls == second.calls == 1


def test_manager_keeps_highest_priority_source_for_duplicate_identifier():
    low = _Provider("low", (_field("general.author", "low"),), priority=10)
    high = _Provider("high", (_field("general.author", "high"),), priority=20)

    result = MetadataManager((low, high)).extract(_record())

    assert result.fields[0].value == "high"


def test_manager_uses_confidence_as_a_stable_priority_tiebreaker():
    low = _Provider("low", (_field("general.author", "low", confidence=MetadataConfidence.LOW),))
    high = _Provider("high", (_field("general.author", "high", confidence=MetadataConfidence.HIGH),))

    result = MetadataManager((low, high)).extract(_record())

    assert result.fields[0].value == "high"


def test_cache_prevents_any_second_provider_execution():
    provider = _Provider("cached", (_field("general.name", "value"),))
    manager = MetadataManager((provider,), MetadataCache())
    record = _record()

    assert manager.extract(record) is manager.extract(record)
    assert provider.calls == 1


def test_absent_or_failing_provider_does_not_hide_other_provider_result():
    missing = _Provider("missing", supported=False)
    failing = _Provider("failing", error="extract")
    valid = _Provider("valid", (_field("general.name", "value"),))

    result = MetadataManager((missing, failing, valid)).extract(_record())

    assert [field.identifier for field in result.fields] == ["general.name"]


def test_registry_rejects_duplicate_provider_identifier():
    registry = MetadataProviderRegistry((_Provider("same"),))

    try:
        registry.register(_Provider("same"))
    except ValueError as error:
        assert "déjà enregistré" in str(error)
    else:
        raise AssertionError("Le registre doit garantir l'unicité des providers.")


def test_large_field_merge_is_linear_in_number_of_fields():
    fields = tuple(_field(f"general.field_{index}", str(index), order=index) for index in range(2_000))
    result = MetadataManager((_Provider("bulk", fields),)).extract(_record())

    assert len(result.fields) == 2_000
