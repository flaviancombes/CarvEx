"""Tests de contrats des providers de métadonnées spécialisés."""

from __future__ import annotations

import struct
import wave
import zipfile
from uuid import uuid4

from pypdf import PdfWriter

from metadata.archive import ArchiveMetadataExtractor
from metadata.audio import AudioMetadataExtractor
from metadata.executable import ExecutableMetadataExtractor
from metadata.manager import build_default_manager
from metadata.office import OfficeMetadataExtractor
from metadata.pdf import PdfMetadataExtractor
from metadata.video import VideoMetadataExtractor


def _record(path, mime: str = ""):
    return {"file_id": str(uuid4()), "name": path.name, "output": str(path), "mime": mime}


def _identifiers(fields):
    return {field.identifier for field in fields}


def test_pdf_provider_extracts_document_properties_and_pages(tmp_path):
    path = tmp_path / "evidence.pdf"
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_metadata({"/Title": "Titre", "/Author": "Alice", "/Producer": "CarvEx test"})
    with path.open("wb") as stream:
        writer.write(stream)

    identifiers = _identifiers(PdfMetadataExtractor().extract(_record(path, "application/pdf")))

    assert {"pdf.title", "pdf.author", "pdf.pages"} <= identifiers


def test_office_provider_extracts_core_custom_and_forensic_properties(tmp_path):
    path = tmp_path / "evidence.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "docProps/core.xml", "<root><creator>Alice</creator><title>Rapport</title><revision>3</revision></root>"
        )
        archive.writestr("docProps/app.xml", "<root><Company>CarvEx</Company></root>")
        archive.writestr("docProps/custom.xml", '<root><property name="Dossier"><value>DFIR</value></property></root>')
        archive.writestr("word/vbaProject.bin", b"macro")
        archive.writestr("word/comments.xml", "<comments />")

    identifiers = _identifiers(OfficeMetadataExtractor().extract(_record(path)))

    assert {
        "office.author",
        "office.company",
        "office.custom.dossier",
        "office.macros",
        "office.comments",
    } <= identifiers


def test_audio_provider_extracts_wav_technical_metadata(tmp_path):
    path = tmp_path / "evidence.wav"
    with wave.open(str(path), "wb") as source:
        source.setnchannels(2)
        source.setsampwidth(2)
        source.setframerate(44_100)
        source.writeframes(b"\0\0" * 4_410)

    identifiers = _identifiers(AudioMetadataExtractor().extract(_record(path, "audio/wav")))

    assert {"audio.duration", "audio.sample_rate", "audio.channels"} <= identifiers


def test_archive_provider_limits_listing_and_reports_encryption(tmp_path):
    path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.txt", "one")
        archive.writestr("two.txt", "two")
        archive.comment = b"comment"

    identifiers = _identifiers(ArchiveMetadataExtractor().extract(_record(path)))

    assert {"archive.entries", "archive.contents", "archive.comment", "archive.encrypted"} <= identifiers


def test_executable_provider_extracts_elf_and_pe_headers(tmp_path):
    elf = tmp_path / "evidence.elf"
    elf.write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 11 + struct.pack("<H", 62) + b"\0" * 20)
    pe = tmp_path / "evidence.exe"
    payload = bytearray(512)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", payload, 0x84, 0x8664, 0, 123, 0, 0, 0, 0)
    pe.write_bytes(payload)

    provider = ExecutableMetadataExtractor()
    assert {"executable.format", "executable.architecture"} <= _identifiers(provider.extract(_record(elf)))
    assert {"executable.format", "pe.compilation_timestamp"} <= _identifiers(provider.extract(_record(pe)))


def test_video_provider_and_invalid_inputs_are_silent(tmp_path):
    path = tmp_path / "corrupt.mp4"
    path.write_bytes(b"not a movie")

    assert VideoMetadataExtractor().extract(_record(path, "video/mp4")) == ()
    assert PdfMetadataExtractor().extract(_record(path, "application/pdf")) == ()


def test_default_manager_registers_all_production_providers():
    manager = build_default_manager()

    assert {provider.provider_id for provider in manager._registry.providers} == {
        "pillow.image",
        "pypdf.pdf",
        "builtin.office",
        "mutagen.video",
        "mutagen.audio",
        "stdlib.archive",
        "builtin.executable",
        "generic.unavailable",
    }
