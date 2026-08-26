import sys
from collections.abc import Callable
from pathlib import Path

from core.duplicates import DuplicateCounter
from core.exporter import Exporter
from core.import_progress import ImportProgress, ImportProgressReporter
from core.scanner import Scanner
from models.report import Report
from report.html_report import HTMLReport


def generate_photorec_report(
    source: str | Path,
    destination: str | Path,
    *,
    progress_callback: Callable[[ImportProgress], None] | None = None,
) -> Report:
    """Build the CarvEx report from a PhotoRec directory incrementally."""
    source_path = Path(source)
    destination_path = Path(destination)
    progress = ImportProgressReporter(progress_callback)
    scanner = Scanner(source_path)
    progress.report("scan", "Analyse des fichiers...")
    total = scanner.count_files()
    progress.report("scan", "Analyse des fichiers...", total, total)
    exporter = Exporter(destination_path)
    duplicates = DuplicateCounter()
    report = Report(retain_files=False)
    report_directory = destination_path / "reports"
    report_writer = HTMLReport().begin_stream(report_directory)
    try:
        progress.report("export", "Traitement, classement et indexation...", 0, total)
        for completed, recovered_file in enumerate(scanner.iter_scan(total=total), start=1):
            exporter.export(recovered_file)
            duplicates.add(recovered_file.sha256)
            report.add(recovered_file)
            report_writer.append(recovered_file)
            progress.report("export", "Traitement, classement et indexation...", completed, total)
        report.duplicates = duplicates.group_count
        progress.report("report", "Finalisation du rapport...", 0, 1)
        report_writer.finalize(report.duplicate_count)
        progress.report("report", "Finalisation du rapport...", 1, 1)
    except Exception:
        report_writer.abort()
        raise
    return report


def main() -> None:
    if len(sys.argv) != 3:
        print("\nCarvEx\n\nUtilisation :\n\npy carvex.py <source> <destination>")
        return

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])

    def show_progress(update: ImportProgress) -> None:
        percent = f" {update.percent}%" if update.percent is not None else ""
        detail = f" ({update.completed} / {update.total})" if update.completed is not None else ""
        print(f"{update.message}{percent}{detail}")

    report = generate_photorec_report(source, destination, progress_callback=show_progress)
    print("\n" + "=" * 40 + "\n\nAnalyse termin\\u00e9e\n")
    print("Fichiers :", report.total_files)
    print("Doublons :", report.duplicate_count)
    print("Rapport :", destination / "reports" / "index.html")


if __name__ == "__main__":
    main()
