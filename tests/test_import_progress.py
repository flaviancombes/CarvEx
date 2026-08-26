from __future__ import annotations

from pathlib import Path

import carvex
from core.import_progress import ImportProgress


class _RecoveredFile:
    def __init__(self, name: str) -> None:
        self.filename = name
        self.path = Path(name)
        self.source_path = self.path
        self.source_directory = "source"
        self.mime = "image/jpeg"
        self.size = 1
        self.sha256 = ""
        self.output_path = None
        self.category = ""


def test_pipeline_emits_a_single_shared_progress_stream(monkeypatch, tmp_path):
    files = [_RecoveredFile("one.jpg"), _RecoveredFile("two.jpg")]

    class Scanner:
        def __init__(self, _source) -> None:
            pass

        def count_files(self):
            return 2

        def iter_scan(self, *, total):
            assert total == 2
            return iter(files)

    class Exporter:
        def __init__(self, _destination) -> None:
            pass

        def export(self, file) -> None:
            file.sha256 = file.filename
            file.category = "Images"
            file.output_path = Path(file.filename)

    class HtmlReport:
        class Writer:
            def append(self, _file) -> None:
                pass

            def finalize(self, _duplicate_count) -> None:
                pass

            def abort(self) -> None:
                pass

        def begin_stream(self, _destination):
            return self.Writer()

    monkeypatch.setattr(carvex, "Scanner", Scanner)
    monkeypatch.setattr(carvex, "Exporter", Exporter)
    monkeypatch.setattr(carvex, "HTMLReport", HtmlReport)
    updates: list[ImportProgress] = []

    carvex.generate_photorec_report(tmp_path, tmp_path / "project", progress_callback=updates.append)

    assert [(item.phase, item.completed, item.total) for item in updates] == [
        ("scan", None, None),
        ("scan", 2, 2),
        ("export", 0, 2),
        ("export", 1, 2),
        ("export", 2, 2),
        ("report", 0, 1),
        ("report", 1, 1),
    ]
