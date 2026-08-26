"""
CarvEx
Exporter
"""

import shutil
from pathlib import Path

from core.classifier import Classifier
from core.hashing import Hasher


class Exporter:

    def __init__(self, output_directory: Path):

        self.output = Path(output_directory)

    def export(self, recovered_file):

        category, subtype = Classifier.destination(
            recovered_file.mime,
            recovered_file.extension,
        )

        destination = self.output / category / subtype

        destination.mkdir(parents=True, exist_ok=True)

        filename = recovered_file.filename

        target = destination / filename

        counter = 1

        while target.exists():

            target = destination / (f"{target.stem}_{counter}" f"{target.suffix}")

            counter += 1

        shutil.copy2(recovered_file.path, target)
        recovered_file.sha256 = Hasher.sha256(target)

        recovered_file.output_path = target

        recovered_file.category = category

        return target
