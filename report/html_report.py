"""Safe, progressive CarvEx report generation."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any


class StreamingReportWriter:
    """Write processed records to a temporary JSON document incrementally."""

    def __init__(self, report: HTMLReport, destination: Path) -> None:
        self._report = report
        self._destination = destination
        self._destination.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination,
            prefix=".report-data-",
            suffix=".tmp",
            delete=False,
        )
        self._temporary_path = Path(self._temporary.name)
        self._temporary.write('{"report_version":2,"files":[')
        self._count = 0
        self._total_size = 0
        self._categories: Counter[str] = Counter()
        self._closed = False

    def append(self, file: Any) -> None:
        if self._closed:
            raise RuntimeError("The streaming report is already closed.")
        if self._count:
            self._temporary.write(",")
        json.dump(self._report._record_for(file), self._temporary, ensure_ascii=False, separators=(",", ":"))
        self._count += 1
        self._total_size += file.size
        self._categories[file.category] += 1

    def finalize(self, duplicate_count: int) -> None:
        if self._closed:
            return
        try:
            self._temporary.write("]")
            self._report._write_json_property(self._temporary, "total_files", self._count, prefix=",")
            self._report._write_json_property(self._temporary, "total_size", self._total_size, prefix=",")
            self._report._write_json_property(self._temporary, "duplicates", duplicate_count, prefix=",")
            self._report._write_json_property(self._temporary, "categories", dict(self._categories), prefix=",")
            self._temporary.write("}")
            self._temporary.flush()
            os.fsync(self._temporary.fileno())
            self._temporary.close()
            os.replace(self._temporary_path, self._destination / self._report.DATA_FILENAME)
            self._report._copy_presentation(self._destination)
            self._closed = True
        except Exception:
            self.abort()
            raise

    def abort(self) -> None:
        if self._closed:
            return
        self._temporary.close()
        self._temporary_path.unlink(missing_ok=True)
        self._closed = True


class HTMLReport:
    """Write static presentation files and non-executable JSON data."""

    DATA_FILENAME = "report-data.json"
    REPORT_VERSION = 2

    def __init__(self) -> None:
        self.template_dir = resources.files("reports")

    def begin_stream(self, destination: Path) -> StreamingReportWriter:
        """Open a progressive report; each append serializes one record."""
        return StreamingReportWriter(self, destination)

    def generate(
        self,
        report,
        destination: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        """Compatibility API for existing in-memory reports."""
        files = report.files
        if files is None:
            raise ValueError("A report without retained files must be generated with begin_stream().")
        writer = self.begin_stream(destination)
        try:
            total = len(files)
            if progress_callback is not None:
                progress_callback(0, total)
            for completed, file in enumerate(files, start=1):
                writer.append(file)
                if progress_callback is not None and completed < total:
                    progress_callback(completed, total)
            writer.finalize(report.duplicate_count)
        except Exception:
            writer.abort()
            raise
        if progress_callback is not None:
            progress_callback(total, total)
        print(f"Rapport HTML g\\u00e9n\\u00e9r\\u00e9 : {destination / 'index.html'}")

    def _copy_presentation(self, destination: Path) -> None:
        for source_name, destination_name in (
            ("template.html", "index.html"),
            ("style.css", "style.css"),
            ("app.js", "app.js"),
        ):
            resource = self.template_dir.joinpath(source_name)
            if not resource.is_file():
                raise FileNotFoundError(resource)
            with resources.as_file(resource) as source_path:
                shutil.copy2(source_path, destination / destination_name)

    @staticmethod
    def _write_json_property(stream, name: str, value: Any, *, prefix: str = "") -> None:
        stream.write(prefix)
        json.dump(name, stream, ensure_ascii=False)
        stream.write(":")
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _record_for(file: Any) -> dict[str, Any]:
        return {
            "name": file.filename,
            "category": file.category,
            "mime": file.mime,
            "size": file.size,
            "sha256": file.sha256,
            "output": str(file.output_path.resolve()) if file.output_path else "",
            "source_path": str((file.source_path or file.path).resolve()),
            "source_directory": file.source_directory or file.path.parent.name,
        }
