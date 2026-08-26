from __future__ import annotations

import wave
import zipfile
from pathlib import Path

from PySide6.QtCore import QSize

from ui.preview_panel import PreviewPanel
from ui.preview_providers import (
    ArchivePreviewProvider,
    ExecutablePreviewProvider,
    FallbackPreviewProvider,
    MediaPreviewProvider,
    OfficePreviewProvider,
    PreviewProviderRegistry,
    PreviewRequest,
    PreviewResult,
    TextPreviewProvider,
)


def _request(path: Path | None, mime: str = "") -> PreviewRequest:
    return PreviewRequest({"mime": mime, "size": path.stat().st_size if path else 0}, path, mime, QSize(640, 480))


def test_text_provider_reads_a_bounded_sample_and_reports_statistics(tmp_path):
    path = tmp_path / "evidence.txt"
    path.write_text("first line\nsecond line\n", encoding="utf-8")

    result = TextPreviewProvider().load(_request(path, "text/plain"))

    assert "first line" in result.body
    assert ("Encodage", "utf-8") in result.details
    assert ("Lignes", "2") in result.details


def test_text_provider_limits_statistics_for_very_large_files(tmp_path):
    path = tmp_path / "large.txt"
    with path.open("wb") as output:
        output.write(b"line\n" * (TextPreviewProvider.STATS_BYTES // 5 + 1))

    result = TextPreviewProvider().load(_request(path, "text/plain"))

    assert any(label.startswith("Lignes (premiers") for label, _value in result.details)


def test_office_provider_extracts_docx_properties_and_excerpt(tmp_path):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "docProps/core.xml",
            "<coreProperties><title>Rapport</title><creator>Alice</creator><subject>Analyse</subject></coreProperties>",
        )
        archive.writestr("word/document.xml", "<document><p>Première ligne</p><p>Seconde ligne</p></document>")

    result = OfficePreviewProvider().load(
        _request(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    )

    assert result.description == "Document DOCX"
    assert ("Title", "Rapport") in result.details
    assert "Première ligne" in result.body


def test_office_provider_extracts_odt_properties_and_excerpt(tmp_path):
    path = tmp_path / "report.odt"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("meta.xml", "<document-meta><title>Note</title><creator>Bob</creator></document-meta>")
        archive.writestr("content.xml", "<document-content><p>Contenu ODT</p></document-content>")

    result = OfficePreviewProvider().load(_request(path, "application/vnd.oasis.opendocument.text"))

    assert result.description == "Document ODT"
    assert ("Title", "Note") in result.details
    assert "Contenu ODT" in result.body


def test_archive_provider_lists_entries_without_extracting_them(tmp_path):
    path = tmp_path / "evidence.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.txt", "one")
        archive.writestr("two.txt", "two")

    result = ArchivePreviewProvider().load(_request(path, "application/zip"))

    assert result.details == (("Entrées", "2"),)
    assert "one.txt" in result.body
    assert "two.txt" in result.body


def test_archive_provider_reports_a_corrupted_archive_without_raising(tmp_path):
    path = tmp_path / "broken.zip"
    path.write_bytes(b"broken")

    result = ArchivePreviewProvider().load(_request(path, "application/zip"))

    assert "illisible" in result.body


def test_media_provider_reads_wav_headers_without_decoding_audio(tmp_path):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\0\0" * 8_000)

    result = MediaPreviewProvider().load(_request(path, "audio/wav"))

    assert result.media_kind == "audio"
    assert ("Fréquence", "8000 Hz") in result.details
    assert ("Canaux", "1") in result.details


def test_executable_provider_reads_only_the_header(tmp_path):
    path = tmp_path / "sample.elf"
    path.write_bytes(b"\x7fELF\x02" + b"\0" * 8_192)
    request = PreviewRequest(
        {"category": "Executables", "sha256": "a" * 64}, path, "application/x-elf", QSize(640, 480)
    )

    result = ExecutablePreviewProvider().load(request)

    assert ("Architecture", "ELF 64 bits") in result.details
    assert ("SHA-256", "a" * 64) in result.details


def test_fallback_provider_never_leaves_a_file_without_information():
    result = FallbackPreviewProvider().load(
        PreviewRequest(
            {"mime": "application/x-unknown", "size": 512, "sha256": "hash"}, None, "application/x-unknown", QSize(1, 1)
        )
    )

    assert ("Type MIME", "application/x-unknown") in result.details
    assert ("SHA-256", "hash") in result.details


def test_registry_accepts_a_demonstration_provider_and_panel_uses_it(qtbot):
    class DemoProvider:
        def supports(self, request):
            return request.mime == "application/x-carvex-demo"

        def load(self, _request):
            return PreviewResult(None, "Démonstration", body="Extension chargée")

    registry = PreviewProviderRegistry((FallbackPreviewProvider(),))
    registry.register(DemoProvider())
    panel = PreviewPanel(registry=registry)
    qtbot.addWidget(panel)

    panel.set_file({"mime": "application/x-carvex-demo", "name": "demo"})

    qtbot.waitUntil(lambda: panel.description.text() == "Démonstration")
    assert panel.body.toPlainText() == "Extension chargée"


def test_corrupted_office_document_keeps_preview_panel_responsive(tmp_path, qtbot):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    panel = PreviewPanel()
    qtbot.addWidget(panel)

    panel.set_file(
        {"mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "output": str(path)}
    )

    qtbot.waitUntil(lambda: panel.description.text() == "Aperçu indisponible")
    assert "corrompu" in panel.body.toPlainText()
