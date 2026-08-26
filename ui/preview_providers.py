"""Providers de contenu pour l'aperçu partagé, indépendants des widgets Qt."""

from __future__ import annotations

import codecs
import struct
import tarfile
import wave
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from xml.etree import ElementTree

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader

from utils.performance import format_byte_size


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    """Entrée légère d'un provider ; le fichier n'est jamais chargé par défaut."""

    file_record: Mapping[str, Any]
    path: Path | None
    mime: str
    target_size: QSize


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """Projection bornée transférable du worker vers l'interface Qt."""

    image: QImage | None
    description: str
    details: tuple[tuple[str, str], ...] = ()
    body: str = ""
    media_kind: str | None = None
    media_path: str | None = None


class PreviewProvider(Protocol):
    """Contrat d'extension : aucun provider ne manipule le panneau Qt."""

    def supports(self, request: PreviewRequest) -> bool: ...

    def load(self, request: PreviewRequest) -> PreviewResult: ...


class PreviewProviderRegistry:
    """Résout un provider spécialisé sans condition métier dans l'UI."""

    def __init__(self, providers: tuple[PreviewProvider, ...] = ()) -> None:
        self._providers = list(providers)

    def register(self, provider: PreviewProvider) -> None:
        self._providers.insert(0, provider)

    def resolve(self, request: PreviewRequest) -> PreviewProvider:
        for provider in self._providers:
            if provider.supports(request):
                return provider
        raise LookupError("Aucun provider d'aperçu n'est enregistré.")


class ImagePreviewProvider:
    def supports(self, request: PreviewRequest) -> bool:
        return request.path is not None and request.mime.startswith("image/")

    def load(self, request: PreviewRequest) -> PreviewResult:
        assert request.path is not None
        reader = QImageReader(str(request.path))
        reader.setAutoTransform(True)
        source_size = reader.size()
        if source_size.isValid():
            reader.setScaledSize(source_size.scaled(request.target_size, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        return PreviewResult(image if not image.isNull() else None, f"Image — {request.mime}")


class PdfPreviewProvider:
    def supports(self, request: PreviewRequest) -> bool:
        return request.path is not None and request.mime == "application/pdf"

    def load(self, request: PreviewRequest) -> PreviewResult:
        assert request.path is not None
        from PySide6.QtPdf import QPdfDocument

        document = QPdfDocument()
        document.load(str(request.path))
        if document.pageCount() <= 0:
            return PreviewResult(None, "Document PDF", body="Aperçu de première page indisponible.")
        image = document.render(0, request.target_size)
        return PreviewResult(
            image if not image.isNull() else None,
            "PDF — première page",
            details=(("Pages", str(document.pageCount())),),
        )


class TextPreviewProvider:
    """Lit un échantillon borné et calcule ses statistiques hors thread UI."""

    SAMPLE_BYTES = 128 * 1024
    STATS_BYTES = 8 * 1024 * 1024
    TEXT_SUFFIXES = {
        ".txt",
        ".csv",
        ".json",
        ".xml",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".ts",
        ".py",
        ".php",
        ".java",
        ".c",
        ".cpp",
        ".sh",
        ".bat",
        ".ps1",
        ".yaml",
        ".yml",
    }

    def supports(self, request: PreviewRequest) -> bool:
        return request.path is not None and (
            request.mime.startswith("text/") or request.path.suffix.lower() in self.TEXT_SUFFIXES
        )

    def load(self, request: PreviewRequest) -> PreviewResult:
        assert request.path is not None
        with request.path.open("rb") as source:
            sample = source.read(self.SAMPLE_BYTES)
        encoding = self._detect_encoding(sample)
        text = sample.decode(encoding, errors="replace")
        lines, characters, partial = self._statistics(request.path, encoding)
        suffix = " (premiers 8 MiB)" if partial else ""
        return PreviewResult(
            None,
            f"Texte — {request.mime or 'type détecté par extension'}",
            details=(
                ("Encodage", encoding),
                (f"Lignes{suffix}", str(lines)),
                (f"Caractères{suffix}", str(characters)),
                ("Taille", format_byte_size(request.path.stat().st_size)),
            ),
            body="\n".join(text.splitlines()[:20]),
        )

    @staticmethod
    def _detect_encoding(sample: bytes) -> str:
        for marker, encoding in (
            (codecs.BOM_UTF8, "utf-8-sig"),
            (codecs.BOM_UTF16_LE, "utf-16-le"),
            (codecs.BOM_UTF16_BE, "utf-16-be"),
        ):
            if sample.startswith(marker):
                return encoding
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return "latin-1"
        return "utf-8"

    def _statistics(self, path: Path, encoding: str) -> tuple[int, int, bool]:
        remaining = self.STATS_BYTES
        lines = characters = 0
        with path.open("rb") as source:
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    return lines, characters, False
                decoded = chunk.decode(encoding, errors="replace")
                lines += decoded.count("\n")
                characters += len(decoded)
                remaining -= len(chunk)
        return lines, characters, path.stat().st_size > self.STATS_BYTES


class OfficePreviewProvider:
    """Extrait les propriétés et un extrait textuel de DOCX/ODT sans Office."""

    MAX_XML_BYTES = 2 * 1024 * 1024
    DOCX_MIMES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    ODT_MIMES = {"application/vnd.oasis.opendocument.text"}

    def supports(self, request: PreviewRequest) -> bool:
        return request.path is not None and (
            request.mime in self.DOCX_MIMES | self.ODT_MIMES or request.path.suffix.lower() in {".docx", ".odt"}
        )

    def load(self, request: PreviewRequest) -> PreviewResult:
        assert request.path is not None
        with zipfile.ZipFile(request.path) as archive:
            if request.path.suffix.lower() == ".odt" or request.mime in self.ODT_MIMES:
                metadata = self._xml_values(
                    archive, "meta.xml", {"title": "title", "author": "creator", "subject": "subject"}
                )
                body = self._xml_text(archive, "content.xml")
                label = "Document ODT"
            else:
                metadata = self._xml_values(
                    archive,
                    "docProps/core.xml",
                    {"title": "title", "author": "creator", "subject": "subject"},
                )
                body = self._xml_text(archive, "word/document.xml")
                label = "Document DOCX"
        details = tuple((name.capitalize(), value) for name, value in metadata.items() if value)
        return PreviewResult(None, label, details=details, body=body)

    def _xml_values(self, archive: zipfile.ZipFile, name: str, fields: Mapping[str, str]) -> dict[str, str]:
        try:
            with archive.open(name) as source:
                root = ElementTree.fromstring(source.read(self.MAX_XML_BYTES))
        except (KeyError, ElementTree.ParseError):
            return {}
        values: dict[str, str] = {}
        for field_name, local_name in fields.items():
            element = root.find(f".//{{*}}{local_name}")
            values[field_name] = (element.text or "").strip() if element is not None else ""
        return values

    def _xml_text(self, archive: zipfile.ZipFile, name: str) -> str:
        try:
            with archive.open(name) as source:
                root = ElementTree.fromstring(source.read(self.MAX_XML_BYTES))
        except (KeyError, ElementTree.ParseError):
            return "Extrait textuel indisponible."
        texts = [text.strip() for text in root.itertext() if text and text.strip()]
        return "\n".join(texts)[:32_768]


class ArchivePreviewProvider:
    MAX_ENTRIES = 200
    SUFFIXES = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso", ".apk"}

    def supports(self, request: PreviewRequest) -> bool:
        return request.path is not None and (
            request.mime.startswith("application/zip")
            or request.mime.startswith("application/x-tar")
            or request.path.suffix.lower() in self.SUFFIXES
        )

    def load(self, request: PreviewRequest) -> PreviewResult:
        assert request.path is not None
        try:
            if (
                zipfile.is_zipfile(request.path)
                or request.mime.startswith("application/zip")
                or request.path.suffix.lower() in {".zip", ".apk"}
            ):
                with zipfile.ZipFile(request.path) as archive:
                    names = [entry.filename for entry in archive.infolist()[: self.MAX_ENTRIES]]
                    total = len(archive.infolist())
            elif tarfile.is_tarfile(request.path):
                with tarfile.open(request.path) as archive:
                    members = archive.getmembers()
                    names = [entry.name for entry in members[: self.MAX_ENTRIES]]
                    total = len(members)
            else:
                return PreviewResult(None, "Archive", body="Format d'archive non pris en charge par l'aperçu intégré.")
        except (OSError, tarfile.TarError, zipfile.BadZipFile):
            return PreviewResult(None, "Archive", body="Archive corrompue ou illisible.")
        suffix = f"\n… {total - len(names)} entrées supplémentaires" if total > len(names) else ""
        return PreviewResult(None, "Archive", details=(("Entrées", str(total)),), body="\n".join(names) + suffix)


class MediaPreviewProvider:
    def supports(self, request: PreviewRequest) -> bool:
        return request.path is not None and (request.mime.startswith("audio/") or request.mime.startswith("video/"))

    def load(self, request: PreviewRequest) -> PreviewResult:
        assert request.path is not None
        kind = "audio" if request.mime.startswith("audio/") else "video"
        details: list[tuple[str, str]] = [
            ("Type MIME", request.mime),
            ("Taille", format_byte_size(request.path.stat().st_size)),
        ]
        if request.path.suffix.lower() == ".wav":
            try:
                with wave.open(str(request.path), "rb") as source:
                    duration = source.getnframes() / max(source.getframerate(), 1)
                    details.extend(
                        (
                            ("Durée", f"{duration:.2f} s"),
                            ("Codec", "PCM"),
                            ("Fréquence", f"{source.getframerate()} Hz"),
                            ("Canaux", str(source.getnchannels())),
                            (
                                "Débit",
                                f"{source.getframerate() * source.getnchannels() * source.getsampwidth() * 8} bit/s",
                            ),
                        )
                    )
            except (OSError, wave.Error):
                details.append(("Métadonnées", "Indisponibles"))
        else:
            details.extend((("Durée", "À déterminer par le lecteur"), ("Codec", "À déterminer par le lecteur")))
            if kind == "audio":
                details.extend(
                    (("Fréquence", "À déterminer par le lecteur"), ("Canaux", "À déterminer par le lecteur"))
                )
            else:
                details.extend((("Résolution", "À déterminer par le lecteur"), ("FPS", "À déterminer par le lecteur")))
        return PreviewResult(
            None,
            "Audio" if kind == "audio" else "Vidéo",
            details=tuple(details),
            media_kind=kind,
            media_path=str(request.path),
        )


class ExecutablePreviewProvider:
    def supports(self, request: PreviewRequest) -> bool:
        return request.path is not None and (
            request.file_record.get("category") == "Executables"
            or request.path.suffix.lower() in {".exe", ".dll", ".msi", ".elf"}
        )

    def load(self, request: PreviewRequest) -> PreviewResult:
        assert request.path is not None
        with request.path.open("rb") as source:
            data = source.read(4096)
        details = [
            ("Architecture", self._architecture(data)),
            ("Éditeur", "Indisponible"),
            ("Signature numérique", "Non vérifiée"),
        ]
        if request.file_record.get("sha256"):
            details.append(("SHA-256", str(request.file_record["sha256"])))
        return PreviewResult(None, "Exécutable", details=tuple(details))

    @staticmethod
    def _architecture(data: bytes) -> str:
        if data.startswith(b"\x7fELF") and len(data) > 5:
            return "ELF 64 bits" if data[4] == 2 else "ELF 32 bits" if data[4] == 1 else "ELF inconnu"
        if data.startswith(b"MZ") and len(data) >= 0x40:
            offset = struct.unpack_from("<I", data, 0x3C)[0]
            if offset + 6 <= len(data) and data[offset : offset + 4] == b"PE\0\0":
                machine = struct.unpack_from("<H", data, offset + 4)[0]
                return {0x14C: "PE x86", 0x8664: "PE x64", 0xAA64: "PE ARM64"}.get(machine, "PE inconnu")
        return "Indisponible"


class FallbackPreviewProvider:
    def supports(self, _request: PreviewRequest) -> bool:
        return True

    def load(self, request: PreviewRequest) -> PreviewResult:
        record = request.file_record
        details = [
            ("Type MIME", request.mime or "Inconnu"),
            ("Taille", format_byte_size(record.get("size"))),
            ("SHA-256", str(record.get("sha256") or "Indisponible")),
            ("Chemin", str(record.get("output") or record.get("source_path") or "Indisponible")),
        ]
        return PreviewResult(None, str(record.get("category") or "Fichier"), details=tuple(details))


def build_default_preview_registry() -> PreviewProviderRegistry:
    return PreviewProviderRegistry(
        (
            ImagePreviewProvider(),
            PdfPreviewProvider(),
            TextPreviewProvider(),
            OfficePreviewProvider(),
            ArchivePreviewProvider(),
            MediaPreviewProvider(),
            ExecutablePreviewProvider(),
            FallbackPreviewProvider(),
        )
    )
