from pathlib import Path

from core.scanner import Scanner
from core.exporter import Exporter

scanner = Scanner(
    r"C:\Users\flavi\OneDrive\Bureau\TryPHOTOREC"
)

files = scanner.scan()

exporter = Exporter(
    Path("output")
)

for file in files:

    exporter.export(file)

print(f"{len(files)} fichiers exportés.")