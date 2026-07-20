from pathlib import Path

from core.scanner import Scanner
from core.exporter import Exporter
from core.duplicates import DuplicateDetector

scanner = Scanner(
    r"C:\Users\flavi\OneDrive\Bureau\TryPHOTOREC"
)

files = scanner.scan()

exporter = Exporter(
    Path("output")
)

detector = DuplicateDetector()

for file in files:

    exporter.export(file)

    detector.add(file)

duplicates = detector.duplicates()

print()

print("=" * 60)
print("DOUBLONS")
print("=" * 60)

for sha256, group in duplicates.items():

    print()

    print(sha256)

    for f in group:

        print("   ", f.filename)

print()

print("Nombre de groupes :", len(duplicates))