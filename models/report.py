"""
CarvEx
Report
"""

from collections import Counter
from datetime import datetime


class Report:

    def __init__(self, *, retain_files: bool = True):

        self.generated = datetime.now()

        self.files = [] if retain_files else None

        self._total_files = 0

        self._total_size = 0

        # Liste des groupes de doublons
        self.duplicates = []

    def add(self, recovered_file):

        self._total_files += 1

        self._total_size += recovered_file.size

        if self.files is not None:
            self.files.append(recovered_file)

    @property
    def total_files(self):

        return self._total_files

    @property
    def total_size(self):

        return self._total_size

    @property
    def mime_counter(self):

        counter = Counter()

        for f in self.files or ():
            counter[f.mime] += 1

        return counter

    @property
    def category_counter(self):

        counter = Counter()

        for f in self.files or ():
            counter[f.category] += 1

        return counter

    @property
    def duplicate_count(self):

        return self.duplicates if isinstance(self.duplicates, int) else len(self.duplicates)
