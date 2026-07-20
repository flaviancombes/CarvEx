"""
CarvEx
Case
"""

from pathlib import Path


class Case:

    def __init__(
        self,
        source: Path,
        destination: Path
    ):

        self.source = Path(source)

        self.destination = Path(destination)

        self.files = []

        self.duplicates = {}

        self.report = None

    def add_file(self, recovered_file):

        self.files.append(recovered_file)

    @property
    def total_files(self):

        return len(self.files)

    @property
    def total_size(self):

        return sum(
            f.size
            for f in self.files
        )