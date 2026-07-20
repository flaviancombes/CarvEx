"""
CarvEx
Report
"""

from datetime import datetime
from collections import Counter


class Report:

    def __init__(self):

        self.generated = datetime.now()

        self.files = []

        # Liste des groupes de doublons
        self.duplicates = []

    def add(self, recovered_file):

        self.files.append(recovered_file)

    @property
    def total_files(self):

        return len(self.files)

    @property
    def total_size(self):

        return sum(f.size for f in self.files)

    @property
    def mime_counter(self):

        counter = Counter()

        for f in self.files:
            counter[f.mime] += 1

        return counter

    @property
    def category_counter(self):

        counter = Counter()

        for f in self.files:
            counter[f.category] += 1

        return counter

    @property
    def duplicate_count(self):

        return len(self.duplicates)