import json
from types import SimpleNamespace

from core.report_loader import ReportLoader
from models.models import RecoveredFile
from models.report import Report
from report.html_report import HTMLReport


def test_html_report_separates_user_data_from_the_static_page(tmp_path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("CarvEx", encoding="utf-8")
    report = Report()
    report.add(
        RecoveredFile(
            path=source,
            filename=source.name,
            extension=".txt",
            mime="text/plain",
            size=source.stat().st_size,
            category="Documents",
            sha256="a" * 64,
        )
    )

    destination = tmp_path / "report"
    HTMLReport().generate(report, destination)

    html = (destination / "index.html").read_text(encoding="utf-8")
    payload = json.loads((destination / "report-data.json").read_text(encoding="utf-8"))

    assert "source.txt" not in html
    assert "reportData" not in html
    assert payload["report_version"] == 2
    assert payload["files"][0]["name"] == "source.txt"
    assert ReportLoader.load(destination).files[0]["name"] == "source.txt"


def test_report_data_keeps_hostile_unicode_values_out_of_html(tmp_path) -> None:
    hostile_name = '</script><script>alert("xss")</script>—é漢字.txt'
    source = tmp_path / "source.txt"
    source.write_text("CarvEx", encoding="utf-8")
    report = Report()
    report.add(
        RecoveredFile(
            path=source,
            filename=hostile_name,
            extension=".txt",
            mime="text/plain",
            size=source.stat().st_size,
            category="<img src=x onerror=alert(1)>",
            sha256="b" * 64,
            source_directory="x" * 16_384,
        )
    )

    destination = tmp_path / "report"
    HTMLReport().generate(report, destination)

    html = (destination / "index.html").read_text(encoding="utf-8")
    payload = json.loads((destination / "report-data.json").read_text(encoding="utf-8"))
    assert hostile_name not in html
    assert "alert(1)" not in html
    assert payload["files"][0]["name"] == hostile_name
    assert payload["files"][0]["source_directory"] == "x" * 16_384


class _LazyFiles:
    def __init__(self, count: int, record) -> None:
        self.count = count
        self.record = record

    def __len__(self) -> int:
        return self.count

    def __iter__(self):
        for index in range(self.count):
            path = self.record.source_path.with_name(f"source-{index}.bin")
            values = dict(self.record.__dict__)
            values.update(source_path=path, path=path)
            yield SimpleNamespace(**values)


class _LargeReport:
    duplicate_count = 0

    def __init__(self, files) -> None:
        self.files = files


def test_report_generation_streams_one_hundred_thousand_records(tmp_path) -> None:
    source = tmp_path / "source.bin"
    record = SimpleNamespace(
        filename="recovered.bin",
        category="Unknown",
        mime="application/octet-stream",
        size=7,
        sha256="c" * 64,
        output_path=None,
        source_path=source,
        path=source,
        source_directory="recup_dir.1",
    )
    report = _LargeReport(_LazyFiles(100_000, record))

    destination = tmp_path / "large-report"
    HTMLReport().generate(report, destination)

    loaded = ReportLoader.load(destination)
    assert len(loaded.files) == 100_000
    assert loaded.payload["total_size"] == 700_000
