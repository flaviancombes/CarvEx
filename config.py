from pathlib import Path

VERSION = "2.0.0"

OUTPUT_DIRECTORY = Path("output")

REPORT_DIRECTORY = Path("reports")

LOG_DIRECTORY = Path("logs")

THREADS = 8

BUFFER_SIZE = 1024 * 1024

IGNORED_FILES = {
    "Thumbs.db",
    "desktop.ini",
    ".DS_Store"
}