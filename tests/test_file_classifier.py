"""Professional MIME-first categories for recovered PhotoRec files."""

from __future__ import annotations

import pytest

from core.classifier import Classifier


@pytest.mark.parametrize(
    ("mime", "extension", "expected"),
    [
        ("application/pdf", ".pdf", ("Documents", "PDF")),
        ("image/heic", ".heic", ("Images", "HEIC")),
        ("video/x-matroska", ".mkv", ("Videos", "MKV")),
        ("audio/flac", ".flac", ("Audio", "FLAC")),
        ("application/x-7z-compressed", ".7z", ("Archives", "7Z")),
        ("application/x-sqlite3", ".sqlite", ("Databases", "SQLite")),
        ("application/x-elf", ".elf", ("Executables", "ELF")),
        ("text/x-python", ".py", ("Code", "PY")),
    ],
)
def test_reliable_mime_selects_each_professional_category(mime, extension, expected):
    assert Classifier.destination(mime, extension) == expected


@pytest.mark.parametrize(
    ("mime", "extension", "expected"),
    [
        ("application/octet-stream", ".mp4", ("Videos", "MP4")),
        ("application/octet-stream", ".m4a", ("Audio", "M4A")),
        ("application/octet-stream", ".cr2", ("Images", "RAW")),
        ("application/octet-stream", ".accdb", ("Databases", "ACCDB")),
        ("application/octet-stream", ".ps1", ("Code", "PS1")),
        ("text/plain", ".ps1", ("Code", "PS1")),
        ("application/x-dosexec", ".dll", ("Executables", "DLL")),
        ("application/x-ole-storage", ".xls", ("Documents", "XLS")),
    ],
)
def test_extension_is_used_as_a_declared_fallback_or_subtype_refinement(mime, extension, expected):
    assert Classifier.destination(mime, extension) == expected


def test_reliable_mime_wins_when_it_contradicts_the_filename_extension():
    assert Classifier.destination("image/png", ".mp4") == ("Images", "PNG")


@pytest.mark.parametrize(
    ("mime", "extension", "expected"),
    [
        ("image/jpeg", ".jpg", ("Images", "JPEG")),
        ("audio/mpeg", ".mp3", ("Audio", "MP3")),
        ("application/x-rar", ".rar", ("Archives", "RAR")),
        ("application/x-sqlite3", ".sqlite", ("Databases", "SQLite")),
        ("application/x-dosexec", ".exe", ("Executables", "EXE")),
    ],
)
def test_common_photorec_signature_mimes_keep_a_useful_destination(mime, extension, expected):
    assert Classifier.destination(mime, extension) == expected


def test_only_genuinely_unrecognised_files_remain_unknown():
    assert Classifier.destination("application/octet-stream", ".mystery") == ("Unknown", "Unknown")
