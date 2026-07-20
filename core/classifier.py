"""
CarvEx
Classifier
"""

from pathlib import Path


class Classifier:

    CATEGORIES = {

        # Images
        "image/jpeg": ("Images", "JPEG"),
        "image/png": ("Images", "PNG"),
        "image/bmp": ("Images", "BMP"),
        "image/gif": ("Images", "GIF"),
        "image/webp": ("Images", "WEBP"),
        "image/avif": ("Images", "AVIF"),
        "image/tiff": ("Images", "TIFF"),

        # Documents
        "application/pdf": ("Documents", "PDF"),
        "application/xml": ("Documents", "XML"),
        "text/plain": ("Documents", "TXT"),
        "application/rtf": ("Documents", "RTF"),
        "application/x-ole-storage": ("Documents", "OLE"),

        # Code
        "text/x-python": ("Code", "Python"),
        "text/x-java-source": ("Code", "Java"),
        "application/jsp": ("Code", "JSP"),
        "text/x-c": ("Code", "C"),
        "text/x-c++": ("Code", "C++"),
        "text/x-fortran": ("Code", "Fortran"),
        "text/html": ("Code", "HTML"),
        "application/json": ("Code", "JSON"),

        # Archives
        "application/zip": ("Archives", "ZIP"),
        "application/gzip": ("Archives", "GZIP"),
        "application/x-rar": ("Archives", "RAR"),
        "application/x-7z-compressed": ("Archives", "7Z"),

        # Bases
        "application/x-sqlite3": ("Databases", "SQLite"),

        # Executables
        "application/x-dosexec": ("Executables", "Windows"),
        "application/x-elf": ("Executables", "Linux"),
    }

    @classmethod
    def destination(cls, mime: str):

        return cls.CATEGORIES.get(
            mime,
            ("Unknown", "Unknown")
        )