"""Progressive discovery and construction of PhotoRec files."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path

import filetype

from config import IGNORED_FILES, THREADS
from models.models import RecoveredFile
from utils.content_analyzer import ContentAnalyzer
from utils.signatures import detect_signature


class Scanner:
    """Scan a directory without materializing its full path list."""

    _BATCH_SIZE = max(THREADS * 16, 64)

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if not self.root.exists():
            raise FileNotFoundError(root)

    def count_files(self) -> int:
        """Count exportable entries for exact progress without retaining paths."""
        return sum(1 for _path in self._iter_paths())

    def iter_scan(
        self,
        *,
        total: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Iterator[RecoveredFile]:
        """Yield records from bounded batches of paths and worker results."""
        discovered_total = self.count_files() if total is None else total
        if progress_callback is not None:
            progress_callback(0, discovered_total)

        completed = 0
        path_iterator = self._iter_paths()
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            while batch := tuple(islice(path_iterator, self._BATCH_SIZE)):
                for recovered_file in executor.map(self._build, batch):
                    completed += 1
                    if progress_callback is not None:
                        progress_callback(completed, discovered_total)
                    yield recovered_file

    def scan(self, progress_callback: Callable[[int, int], None] | None = None) -> list[RecoveredFile]:
        """Compatibility API for callers that explicitly require a materialized list."""
        total = self.count_files()
        return list(self.iter_scan(total=total, progress_callback=progress_callback))

    def _iter_paths(self) -> Iterator[Path]:
        for path in self.root.rglob("*"):
            if path.is_file() and path.name not in IGNORED_FILES:
                yield path

    def _detect_type(self, path: Path) -> tuple[str, str]:
        result = detect_signature(path)
        if result:
            return result

        kind = filetype.guess(path)
        if kind:
            return kind.mime, "." + kind.extension

        extension = path.suffix.lower()
        text_mimes = {
            ".txt": "text/plain",
            ".xml": "application/xml",
            ".ini": "text/plain",
            ".java": "text/x-java-source",
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".csv": "text/csv",
            ".log": "text/plain",
            ".bat": "application/x-bat",
            ".cmd": "application/x-bat",
            ".ps1": "text/plain",
            ".py": "text/x-python",
            ".c": "text/x-c",
            ".cpp": "text/x-c++",
            ".hpp": "text/x-c++",
            ".cs": "text/x-csharp",
            ".php": "application/x-httpd-php",
            ".jsp": "application/jsp",
            ".asp": "text/asp",
            ".aspx": "text/asp",
            ".sql": "application/sql",
            ".md": "text/markdown",
            ".yml": "text/yaml",
            ".yaml": "text/yaml",
            ".sh": "application/x-sh",
            ".psm1": "text/plain",
            ".h": "text/x-c",
            ".f": "text/x-fortran",
            ".f90": "text/x-fortran",
            ".f95": "text/x-fortran",
        }
        analyzed = ContentAnalyzer.analyze(path)
        return analyzed or (text_mimes.get(extension, "application/octet-stream"), extension)

    def _build(self, path: Path) -> RecoveredFile:
        mime, extension = self._detect_type(path)
        return RecoveredFile(
            path=path,
            filename=path.name,
            extension=extension,
            mime=mime,
            size=path.stat().st_size,
            source_path=path,
            source_directory=path.parent.name,
        )
