"""
CarvEx
Scanner

Scanne un dossier PhotoRec et construit une liste
de RecoveredFile.
"""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List
from utils.signatures import detect_signature
from tqdm import tqdm
import filetype
from utils.content_analyzer import ContentAnalyzer

from models.models import RecoveredFile
from config import THREADS, IGNORED_FILES


class Scanner:

    def __init__(self, root: str):

        self.root = Path(root)

        if not self.root.exists():
            raise FileNotFoundError(root)

    ############################################################

    def _list_files(self):

        files = []

        for file in self.root.rglob("*"):

            if not file.is_file():
                continue

            if file.name in IGNORED_FILES:
                continue

            files.append(file)

        return files

    ############################################################

    def _detect_type(self, path: Path):

        result = detect_signature(path)

        if result:
            return result

        kind = filetype.guess(path)

        if kind:
            return kind.mime, "." + kind.extension

        extension = path.suffix.lower()

        TEXT = {
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
            ".hpp": "text/x-c++",
            ".f": "text/x-fortran",
            ".f90": "text/x-fortran",
            ".f95": "text/x-fortran",
        }

        mime = TEXT.get(
            extension,
            "application/octet-stream"
        )

        result = ContentAnalyzer.analyze(path)

        if result:
            return result

        return mime, extension

    ############################################################

    def _build(self, path: Path):

        mime, extension = self._detect_type(path)

        return RecoveredFile(

            path=path,

            filename=path.name,

            extension=extension,

            mime=mime,

            size=path.stat().st_size,

            source_path=path,

            source_directory=path.parent.name

        )

    ############################################################

    def scan(self) -> List[RecoveredFile]:

        paths = self._list_files()

        recovered = []

        with ThreadPoolExecutor(
            max_workers=THREADS
        ) as executor:

            results = executor.map(
                self._build,
                paths
            )

            for file in tqdm(
                results,
                total=len(paths),
                desc="Scanning"
            ):

                recovered.append(file)

        return recovered
