from __future__ import annotations

from core.duplicates import DuplicateIndex


def _record(file_id: str, sha256: str | None) -> dict[str, str]:
    record = {"file_id": file_id, "name": f"{file_id}.jpg"}
    if sha256 is not None:
        record["sha256"] = sha256
    return record


def test_duplicate_index_returns_constant_time_groups_without_copying_records():
    first = _record("f4eaa4d1-cf9b-4884-b05b-5c53750636f5", "a" * 64)
    second = _record("4f6294bb-d88d-42c6-bb16-51fbee36a673", "A" * 64)
    unique = _record("6e3d9190-c2d2-4dfc-a2e8-782157e28f95", "b" * 64)
    index = DuplicateIndex()

    index.build((first, second, unique))

    assert index.is_duplicate(first["file_id"])
    assert index.copy_count(first["file_id"]) == 2
    assert index.members_for(second["file_id"]) == (first["file_id"], second["file_id"])
    assert not index.is_duplicate(unique["file_id"])
    assert index.copy_count(unique["file_id"]) == 1
    assert index.group_count == 1
    assert set(first) == {"file_id", "name", "sha256"}


def test_duplicate_index_ignores_missing_hashes_and_scales_linearly():
    records = [
        _record(f"00000000-0000-4000-8000-{number:012d}", "same" if number % 2 else None) for number in range(1_000)
    ]
    index = DuplicateIndex()

    index.build(records)

    assert index.group_count == 1
    assert index.copy_count(records[1]["file_id"]) == 500
    assert index.copy_count(records[0]["file_id"]) == 1
