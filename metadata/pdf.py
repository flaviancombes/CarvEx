"""Extraction PDF via pypdf, sans dépendance vers l'aperçu Qt."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataCategory, MetadataConfidence, MetadataField


class PdfMetadataExtractor(BaseMetadataExtractor):
    provider_id = "pypdf.pdf"
    priority = 100
    _MIMES = {"application/pdf", "application/x-pdf"}

    def supports(self, file_record: FileRecord) -> bool:
        path = self.existing_path(file_record)
        return str(file_record.get("mime") or "").casefold() in self._MIMES or self._suffix(file_record, path) == ".pdf"

    def extract(self, file_record: FileRecord) -> tuple[MetadataField, ...]:
        path = self.existing_path(file_record)
        if path is None:
            return ()
        try:
            reader = PdfReader(path, strict=False)
            fields = self._document_fields(reader)
            if reader.is_encrypted:
                fields.append(self._field("pdf.encrypted", "Chiffrement", "Oui", 10, MetadataCategory.FORENSIC))
                if reader.decrypt("") == 0:
                    return tuple(fields)
            fields.extend(self._content_fields(reader))
            fields.extend(self._xmp_fields(reader))
            return tuple(fields)
        except (OSError, PdfReadError, ValueError, KeyError, TypeError):
            return ()

    def _document_fields(self, reader: PdfReader) -> list[MetadataField]:
        metadata = reader.metadata or {}
        values = (
            ("pdf.title", "Titre", metadata.get("/Title")),
            ("pdf.author", "Auteur", metadata.get("/Author")),
            ("pdf.subject", "Sujet", metadata.get("/Subject")),
            ("pdf.creator", "Créateur", metadata.get("/Creator")),
            ("pdf.producer", "Producteur", metadata.get("/Producer")),
            ("pdf.creation_date", "Date de création", metadata.get("/CreationDate")),
            ("pdf.modification_date", "Date de modification", metadata.get("/ModDate")),
        )
        fields = [
            self._field(identifier, label, str(value), index * 10)
            for index, (identifier, label, value) in enumerate(values, 1)
            if value
        ]
        header = getattr(reader, "pdf_header", None)
        if header:
            fields.append(self._field("pdf.version", "Version PDF", str(header), 80))
        return fields

    def _xmp_fields(self, reader: PdfReader) -> list[MetadataField]:
        xmp = getattr(reader, "xmp_metadata", None)
        if xmp is None:
            return []
        values = (
            ("xmp.pdf.title", "Titre XMP", getattr(xmp, "dc_title", None)),
            ("xmp.pdf.creator", "Créateur XMP", getattr(xmp, "dc_creator", None)),
            ("xmp.pdf.description", "Description XMP", getattr(xmp, "dc_description", None)),
        )
        return [
            self._field(identifier, label, str(value), 200 + index * 10, MetadataCategory.XMP)
            for index, (identifier, label, value) in enumerate(values)
            if value
        ]

    def _content_fields(self, reader: PdfReader) -> list[MetadataField]:
        fields = [self._field("pdf.pages", "Pages", len(reader.pages), 100)]
        attachments = getattr(reader, "attachments", {})
        if attachments:
            fields.append(
                self._field("pdf.attachments", "Pièces jointes", len(attachments), 110, MetadataCategory.FORENSIC)
            )
        raw = self._raw_bytes(reader)
        if b"/Type /Sig" in raw or b"/FT /Sig" in raw:
            fields.append(self._field("pdf.signatures", "Signatures", "Présentes", 120, MetadataCategory.FORENSIC))
        return fields

    @staticmethod
    def _raw_bytes(reader: PdfReader) -> bytes:
        stream = reader.stream
        position = stream.tell()
        try:
            stream.seek(0)
            return stream.read(8 * 1024 * 1024)
        finally:
            stream.seek(position)

    @staticmethod
    def _suffix(file_record: FileRecord, path: Path | None) -> str:
        return (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).casefold()

    @staticmethod
    def _field(
        identifier: str, label: str, value: str | int, order: int, category: MetadataCategory = MetadataCategory.PDF
    ) -> MetadataField:
        return MetadataField(
            identifier=identifier,
            category=category,
            display_name=label,
            value=value,
            source="pypdf.pdf",
            confidence=MetadataConfidence.HIGH,
            display_order=order,
        )
