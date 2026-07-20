from pathlib import Path
import sys

from models.case import Case
from core.scanner import Scanner
from core.exporter import Exporter
from models.report import Report
from report.html_report import HTMLReport
from core.duplicates import DuplicateDetector


def main():

    if len(sys.argv) != 3:

        print()

        print("CarvEx")

        print()

        print("Utilisation :")

        print("py carvex.py <source> <destination>")

        return

    source = Path(sys.argv[1])

    destination = Path(sys.argv[2])

    case = Case(
        source,
        destination
    )

    print("[1/6] Scan...")

    scanner = Scanner(source)

    files = scanner.scan()

    print("[2/6] Export...")

    exporter = Exporter(destination)

    detector = DuplicateDetector()

    report = Report()

    for file in files:

        exporter.export(file)

        detector.add(file)

        report.add(file)

        case.add_file(file)

    case.duplicates = detector.duplicates()

    report.duplicates = case.duplicates

    case.report = report

    print("[3/6] Rapport...")

    HTMLReport().generate(
        report,
        destination / "reports"
    )

    print()

    print("=" * 40)

    print("Analyse terminée")

    print()

    print("Fichiers :", case.total_files)

    print("Doublons :", len(case.duplicates))

    print("Rapport :", destination / "reports" / "index.html")


if __name__ == "__main__":

    main()