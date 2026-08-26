"""Declarative MIME-first classification for recovered files."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Classification:
    category: str
    subtype: str
    extension_can_refine: bool = False


def _rules(category: str, values: dict[str, str]) -> dict[str, _Classification]:
    return {value: _Classification(category, subtype) for value, subtype in values.items()}


def _index(groups: tuple[dict[str, _Classification], ...]) -> dict[str, _Classification]:
    return {mime_or_extension: result for group in groups for mime_or_extension, result in group.items()}


def _legacy_categories(
    mime_index: dict[str, _Classification],
    low_specificity: dict[str, _Classification],
) -> dict[str, tuple[str, str]]:
    return {mime: (result.category, result.subtype) for mime, result in {**mime_index, **low_specificity}.items()}


class Classifier:
    """Classifies by reliable MIME first, then by a declared extension index."""

    MIME_RULES = (
        _rules(
            "Documents",
            {
                "application/pdf": "PDF",
                "application/rtf": "RTF",
                "text/rtf": "RTF",
                "application/msword": "DOC",
                "application/vnd.ms-word.document.macroenabled.12": "DOCX",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
                "application/vnd.oasis.opendocument.text": "ODT",
                "text/csv": "CSV",
                "application/vnd.ms-excel": "XLS",
                "application/vnd.ms-excel.sheet.macroenabled.12": "XLSX",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
                "application/vnd.ms-powerpoint": "PPT",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
            },
        ),
        _rules(
            "Images",
            {
                "image/jpeg": "JPEG",
                "image/png": "PNG",
                "image/gif": "GIF",
                "image/bmp": "BMP",
                "image/tiff": "TIFF",
                "image/heic": "HEIC",
                "image/heif": "HEIC",
                "image/webp": "WEBP",
                "image/avif": "AVIF",
                "image/x-canon-cr2": "RAW",
                "image/x-nikon-nef": "RAW",
                "image/x-adobe-dng": "RAW",
            },
        ),
        _rules(
            "Videos",
            {
                "video/mp4": "MP4",
                "video/x-msvideo": "AVI",
                "video/quicktime": "MOV",
                "video/x-matroska": "MKV",
                "video/webm": "WEBM",
                "video/x-ms-wmv": "WMV",
                "video/x-flv": "FLV",
            },
        ),
        _rules(
            "Audio",
            {
                "audio/mpeg": "MP3",
                "audio/wav": "WAV",
                "audio/x-wav": "WAV",
                "audio/aac": "AAC",
                "audio/flac": "FLAC",
                "audio/ogg": "OGG",
                "audio/mp4": "M4A",
                "audio/x-m4a": "M4A",
            },
        ),
        _rules(
            "Archives",
            {
                "application/zip": "ZIP",
                "application/x-rar": "RAR",
                "application/vnd.rar": "RAR",
                "application/x-7z-compressed": "7Z",
                "application/x-iso9660-image": "ISO",
                "application/x-tar": "TAR",
                "application/gzip": "GZ",
                "application/x-gzip": "GZ",
                "application/x-bzip2": "BZ2",
            },
        ),
        _rules(
            "Databases",
            {
                "application/x-sqlite3": "SQLite",
                "application/vnd.sqlite3": "SQLite",
                "application/x-msaccess": "MDB",
                "application/vnd.ms-access": "MDB",
            },
        ),
        _rules(
            "Executables",
            {
                "application/vnd.android.package-archive": "APK",
                "application/x-elf": "ELF",
            },
        ),
        _rules(
            "Code",
            {
                "text/html": "HTML",
                "text/css": "CSS",
                "application/javascript": "JS",
                "text/javascript": "JS",
                "application/json": "JSON",
                "application/xml": "XML",
                "text/xml": "XML",
                "text/yaml": "YAML",
                "application/x-yaml": "YAML",
                "text/x-python": "PY",
                "text/x-java-source": "JAVA",
                "text/x-c": "C",
                "text/x-c++": "CPP",
                "application/x-sh": "SH",
                "application/x-bat": "BAT",
                "application/x-httpd-php": "PHP",
                "application/jsp": "JSP",
                "application/sql": "SQL",
            },
        ),
    )

    EXTENSION_RULES = (
        _rules(
            "Documents",
            {
                "pdf": "PDF",
                "doc": "DOC",
                "docx": "DOCX",
                "odt": "ODT",
                "rtf": "RTF",
                "txt": "TXT",
                "csv": "CSV",
                "xls": "XLS",
                "xlsx": "XLSX",
                "ppt": "PPT",
                "pptx": "PPTX",
            },
        ),
        _rules(
            "Images",
            {
                "jpg": "JPEG",
                "jpeg": "JPEG",
                "png": "PNG",
                "gif": "GIF",
                "bmp": "BMP",
                "tif": "TIFF",
                "tiff": "TIFF",
                "heic": "HEIC",
                "heif": "HEIC",
                "webp": "WEBP",
                "avif": "AVIF",
                "raw": "RAW",
                "cr2": "RAW",
                "cr3": "RAW",
                "nef": "RAW",
                "arw": "RAW",
                "dng": "RAW",
                "orf": "RAW",
                "rw2": "RAW",
            },
        ),
        _rules(
            "Videos",
            {"mp4": "MP4", "avi": "AVI", "mov": "MOV", "mkv": "MKV", "webm": "WEBM", "wmv": "WMV", "flv": "FLV"},
        ),
        _rules(
            "Audio",
            {"mp3": "MP3", "wav": "WAV", "aac": "AAC", "flac": "FLAC", "ogg": "OGG", "m4a": "M4A"},
        ),
        _rules(
            "Archives",
            {"zip": "ZIP", "rar": "RAR", "7z": "7Z", "iso": "ISO", "tar": "TAR", "gz": "GZ", "bz2": "BZ2"},
        ),
        _rules(
            "Databases",
            {"sqlite": "SQLite", "sqlite3": "SQLite", "db": "DB", "mdb": "MDB", "accdb": "ACCDB"},
        ),
        _rules(
            "Executables",
            {"exe": "EXE", "dll": "DLL", "msi": "MSI", "apk": "APK", "elf": "ELF"},
        ),
        _rules(
            "Code",
            {
                "html": "HTML",
                "htm": "HTML",
                "css": "CSS",
                "js": "JS",
                "ts": "TS",
                "php": "PHP",
                "py": "PY",
                "java": "JAVA",
                "c": "C",
                "cpp": "CPP",
                "cxx": "CPP",
                "h": "C",
                "hpp": "CPP",
                "sh": "SH",
                "bat": "BAT",
                "cmd": "BAT",
                "ps1": "PS1",
                "json": "JSON",
                "xml": "XML",
                "yaml": "YAML",
                "yml": "YAML",
                "sql": "SQL",
                "md": "MD",
            },
        ),
    )

    # These MIME values identify a binary family, but extension supplies its
    # useful subtype (DLL versus EXE, DOC versus XLS, and so on).
    LOW_SPECIFICITY_MIME_RULES = {
        "application/x-ole-storage": _Classification("Documents", "OLE", extension_can_refine=True),
        "application/x-dosexec": _Classification("Executables", "EXE", extension_can_refine=True),
        "text/plain": _Classification("Documents", "TXT", extension_can_refine=True),
    }

    PREFIX_RULES = (
        ("image/", _Classification("Images", "Image", extension_can_refine=True)),
        ("video/", _Classification("Videos", "Video", extension_can_refine=True)),
        ("audio/", _Classification("Audio", "Audio", extension_can_refine=True)),
    )

    MIME_INDEX = _index(MIME_RULES)
    EXTENSION_INDEX = _index(EXTENSION_RULES)
    # Compatibility for callers that consumed the original public mapping.
    CATEGORIES = _legacy_categories(MIME_INDEX, LOW_SPECIFICITY_MIME_RULES)

    @classmethod
    def destination(cls, mime: str | None, extension: str | None = None) -> tuple[str, str]:
        """Return the destination category and subtype without inspecting file contents."""
        normalized_mime = str(mime or "").casefold().strip().split(";", 1)[0]
        normalized_extension = str(extension or "").casefold().strip().lstrip(".")
        extension_result = cls.EXTENSION_INDEX.get(normalized_extension)
        mime_result = cls.MIME_INDEX.get(normalized_mime) or cls.LOW_SPECIFICITY_MIME_RULES.get(normalized_mime)

        if mime_result is None:
            mime_result = next(
                (result for prefix, result in cls.PREFIX_RULES if normalized_mime.startswith(prefix)), None
            )
        if mime_result is None:
            return cls._destination_from_extension(extension_result)
        if mime_result.extension_can_refine and extension_result is not None:
            if extension_result.category == mime_result.category or normalized_mime in cls.LOW_SPECIFICITY_MIME_RULES:
                return extension_result.category, extension_result.subtype
        return mime_result.category, mime_result.subtype

    @staticmethod
    def _destination_from_extension(extension_result: _Classification | None) -> tuple[str, str]:
        if extension_result is None:
            return "Unknown", "Unknown"
        return extension_result.category, extension_result.subtype
