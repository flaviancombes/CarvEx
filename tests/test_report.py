from pathlib import Path

from core.scanner import Scanner
from core.exporter import Exporter
from models.report import Report
from report.html_report import HTMLReport

scanner = Scanner(
    r"C:\Users\flavi\OneDrive\Bureau\TryPHOTOREC"
)

files = scanner.scan()

exporter = Exporter(
    Path("output")
)

report = Report()

for file in files:

    exporter.export(file)

    report.add(file)

HTMLReport().generate(
    report,
    Path("report.html")
)

print("Rapport généré.")