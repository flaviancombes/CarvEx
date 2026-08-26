from __future__ import annotations

from pathlib import Path

import carvex
from core.scanner import Scanner


class _RecoveredFile:
    def __init__(self, index: int) -> None:
        self.filename = f"f{index:06d}.txt"
        self.path = Path(self.filename)
        self.source_path = self.path
        self.source_directory = "recup_dir.1"
        self.mime = "text/plain"
        self.extension = ".txt"
        self.size = 1
        self.sha256 = ""
        self.output_path = None
        self.category = ""


class _Writer:
    def __init__(self) -> None:
        self.persisted = 0
        self.duplicate_count: int | None = None
        self.aborted = False

    def append(self, _file) -> None:
        self.persisted += 1

    def finalize(self, duplicate_count: int) -> None:
        self.duplicate_count = duplicate_count

    def abort(self) -> None:
        self.aborted = True


def test_pipeline_processes_one_thousand_records_without_scan_or_case_collections(monkeypatch, tmp_path) -> None:
    records = tuple(_RecoveredFile(index) for index in range(1_000))
    writer = _Writer()

    class _Scanner:
        def __init__(self, _source) -> None:
            pass

        def count_files(self) -> int:
            return len(records)

        def iter_scan(self, *, total: int):
            assert total == len(records)
            return iter(records)

        def scan(self, *_args, **_kwargs):
            raise AssertionError("Le pipeline progressif ne doit jamais matérialiser Scanner.scan().")

    class _Exporter:
        def __init__(self, _destination) -> None:
            pass

        def export(self, record) -> None:
            record.sha256 = "same" if record.filename.endswith("0.txt") else record.filename
            record.category = "Documents"
            record.output_path = record.path

    class _Report:
        def begin_stream(self, _destination):
            return writer

    monkeypatch.setattr(carvex, "Scanner", _Scanner)
    monkeypatch.setattr(carvex, "Exporter", _Exporter)
    monkeypatch.setattr(carvex, "HTMLReport", _Report)

    report = carvex.generate_photorec_report(tmp_path, tmp_path / "project")

    assert report.total_files == 1_000
    assert report.files is None
    assert writer.persisted == 1_000
    assert writer.duplicate_count == 1
    assert not writer.aborted


def test_scanner_keeps_path_discovery_bounded_for_one_hundred_thousand_records(tmp_path, monkeypatch) -> None:
    scanner = Scanner(tmp_path)
    produced = 0

    def paths():
        nonlocal produced
        for index in range(100_000):
            produced += 1
            yield Path(f"f{index:06d}.bin")

    monkeypatch.setattr(scanner, "_iter_paths", paths)
    monkeypatch.setattr(scanner, "_build", lambda path: path)

    records = scanner.iter_scan(total=100_000)
    first = next(records)

    assert first == Path("f000000.bin")
    assert produced <= scanner._BATCH_SIZE
    assert 1 + sum(1 for _record in records) == 100_000


def test_pipeline_streams_one_hundred_thousand_records_without_retaining_them(monkeypatch, tmp_path) -> None:
    writer = _Writer()

    class _Scanner:
        def __init__(self, _source) -> None:
            pass

        def count_files(self) -> int:
            return 100_000

        def iter_scan(self, *, total: int):
            assert total == 100_000
            return (_RecoveredFile(index) for index in range(total))

    class _Exporter:
        def __init__(self, _destination) -> None:
            pass

        def export(self, record) -> None:
            record.sha256 = str(record.path)
            record.category = "Documents"
            record.output_path = record.path

    class _Report:
        def begin_stream(self, _destination):
            return writer

    monkeypatch.setattr(carvex, "Scanner", _Scanner)
    monkeypatch.setattr(carvex, "Exporter", _Exporter)
    monkeypatch.setattr(carvex, "HTMLReport", _Report)

    report = carvex.generate_photorec_report(tmp_path, tmp_path / "project")

    assert report.total_files == 100_000
    assert report.files is None
    assert writer.persisted == 100_000
    assert writer.duplicate_count == 0


def test_pipeline_generates_a_report_for_ten_real_files(tmp_path) -> None:
    source = tmp_path / "photorec"
    source.mkdir()
    for index in range(10):
        (source / f"f{index}.txt").write_text(str(index), encoding="utf-8")

    report = carvex.generate_photorec_report(source, tmp_path / "project")

    assert report.total_files == 10
    assert report.files is None
    assert (tmp_path / "project" / "reports" / "report-data.json").is_file()
