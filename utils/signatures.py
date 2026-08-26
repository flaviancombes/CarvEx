"""
CarvEx
Signatures Forensic
"""

from pathlib import Path

# (Signature, MIME, Extension)
SIGNATURES = [
    # ==========================
    # IMAGES
    # ==========================
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"BM", "image/bmp", ".bmp"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"II*\x00", "image/tiff", ".tif"),
    (b"MM\x00*", "image/tiff", ".tif"),
    (b"\x00\x00\x01\x00", "image/x-icon", ".ico"),
    (b"RIFF", "image/webp", ".webp"),  # vérification WEBP faite plus bas
    # ==========================
    # DOCUMENTS
    # ==========================
    (b"%PDF", "application/pdf", ".pdf"),
    (b"{\\rtf", "application/rtf", ".rtf"),
    # ==========================
    # ARCHIVES
    # ==========================
    (b"PK\x03\x04", "application/zip", ".zip"),
    (b"Rar!\x1a\x07", "application/x-rar", ".rar"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed", ".7z"),
    (b"\x1f\x8b", "application/gzip", ".gz"),
    (b"BZh", "application/x-bzip2", ".bz2"),
    # ==========================
    # DATABASE
    # ==========================
    (b"SQLite format 3", "application/x-sqlite3", ".sqlite"),
    # ==========================
    # EXECUTABLES
    # ==========================
    (b"MZ", "application/x-dosexec", ".exe"),
    (b"\x7fELF", "application/x-elf", ".elf"),
    # ==========================
    # AUDIO
    # ==========================
    (b"ID3", "audio/mpeg", ".mp3"),
    (b"fLaC", "audio/flac", ".flac"),
    (b"OggS", "audio/ogg", ".ogg"),
    # ==========================
    # MICROSOFT OLE2
    # ==========================
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage", ".ole"),
]


def detect_signature(path: Path):

    try:

        with open(path, "rb") as f:

            header = f.read(64)

    except Exception:

        return None

    # Cas particulier WEBP
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ("image/webp", ".webp")

    for signature, mime, extension in SIGNATURES:

        if header.startswith(signature):

            return (mime, extension)

    return None
