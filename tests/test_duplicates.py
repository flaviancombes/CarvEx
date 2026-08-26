from pathlib import Path

from core.duplicates import DuplicateCounter, DuplicateDetector
from models.models import RecoveredFile


def _recovered_file(name: str, sha256: str) -> RecoveredFile:
    return RecoveredFile(
        path=Path(name),
        filename=name,
        extension=".txt",
        mime="text/plain",
        size=1,
        sha256=sha256,
    )


def test_duplicate_detector_groups_only_identical_hashes() -> None:
    detector = DuplicateDetector()
    detector.add(_recovered_file("one.txt", "same"))
    detector.add(_recovered_file("two.txt", "same"))
    detector.add(_recovered_file("three.txt", "other"))

    assert [file.filename for file in detector.duplicates()["same"]] == ["one.txt", "two.txt"]
    assert detector.unique()["other"].filename == "three.txt"


def test_duplicate_counter_keeps_only_hash_counts_during_streaming_import() -> None:
    counter = DuplicateCounter()
    counter.add("same")
    counter.add("same")
    counter.add("same")
    counter.add("other")

    assert counter.group_count == 1
