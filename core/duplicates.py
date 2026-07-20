"""
CarvEx
Duplicate detector
"""

from collections import defaultdict


class DuplicateDetector:

    def __init__(self):

        self.index = defaultdict(list)

    def add(self, recovered_file):

        self.index[
            recovered_file.sha256
        ].append(recovered_file)

    def duplicates(self):

        duplicates = {}

        for sha256, files in self.index.items():

            if len(files) > 1:

                duplicates[sha256] = files

        return duplicates

    def unique(self):

        uniques = {}

        for sha256, files in self.index.items():

            if len(files) == 1:

                uniques[sha256] = files[0]

        return uniques