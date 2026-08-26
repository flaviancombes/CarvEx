"""Extraction OOXML et OpenDocument, sans Office ni PreviewProvider."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataCategory, MetadataConfidence, MetadataField


class OfficeMetadataExtractor(BaseMetadataExtractor):
    provider_id = "builtin.office"
    priority = 100
    _SUFFIXES = {".docx", ".xlsx", ".pptx", ".odt", ".ods"}

    def supports(self, file_record: FileRecord) -> bool:
        path = self.existing_path(file_record)
        return self._suffix(file_record, path) in self._SUFFIXES

    def extract(self, file_record: FileRecord) -> tuple[MetadataField, ...]:
        path = self.existing_path(file_record)
        if path is None:
            return ()
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                fields = (
                    self._odf_fields(archive)
                    if self._suffix(file_record, path) in {".odt", ".ods"}
                    else self._ooxml_fields(archive)
                )
                fields.extend(self._structural_fields(names))
                return tuple(fields)
        except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError):
            return ()

    def _ooxml_fields(self, archive: zipfile.ZipFile) -> list[MetadataField]:
        core = self._xml_values(archive, "docProps/core.xml")
        app = self._xml_values(archive, "docProps/app.xml")
        custom = self._custom_values(archive, "docProps/custom.xml")
        values = (
            ("office.title", "Titre", core.get("title")),
            ("office.author", "Auteur", core.get("creator")),
            ("office.last_author", "Dernier auteur", core.get("lastModifiedBy")),
            ("office.subject", "Sujet", core.get("subject")),
            ("office.created", "Créé le", core.get("created")),
            ("office.modified", "Modifié le", core.get("modified")),
            ("office.revision", "Révisions", core.get("revision")),
            ("office.company", "Entreprise", app.get("Company")),
        )
        return self._fields(values, custom)

    def _odf_fields(self, archive: zipfile.ZipFile) -> list[MetadataField]:
        values = self._xml_values(archive, "meta.xml")
        mapped = (
            ("office.title", "Titre", values.get("title")),
            ("office.author", "Auteur", values.get("creator") or values.get("initial-creator")),
            ("office.subject", "Sujet", values.get("subject")),
            ("office.created", "Créé le", values.get("creation-date")),
            ("office.modified", "Modifié le", values.get("date")),
            ("office.revision", "Révisions", values.get("editing-cycles")),
        )
        return self._fields(mapped, {})

    def _structural_fields(self, names: set[str]) -> list[MetadataField]:
        fields: list[MetadataField] = []
        if any(name.casefold().endswith("vbaProject.bin".casefold()) for name in names):
            fields.append(self._field("office.macros", "Macros", "Présentes", 300, MetadataCategory.FORENSIC))
        if any("comment" in name.casefold() for name in names):
            fields.append(self._field("office.comments", "Commentaires", "Présents", 310, MetadataCategory.FORENSIC))
        if any("_xmlsignatures/" in name.casefold() or "origin.sigs" in name.casefold() for name in names):
            fields.append(self._field("office.signatures", "Signatures", "Présentes", 320, MetadataCategory.FORENSIC))
        return fields

    def _fields(self, values, custom: dict[str, str]) -> list[MetadataField]:
        fields = [
            self._field(identifier, label, str(value), index * 10)
            for index, (identifier, label, value) in enumerate(values, 1)
            if value
        ]
        for index, (name, value) in enumerate(sorted(custom.items()), start=100):
            fields.append(self._field(f"office.custom.{name.casefold()}", f"Propriété : {name}", value, index))
        return fields

    @staticmethod
    def _xml_values(archive: zipfile.ZipFile, name: str) -> dict[str, str]:
        try:
            root = ElementTree.fromstring(archive.read(name))
        except KeyError:
            return {}
        values: dict[str, str] = {}
        for element in root.iter():
            if element.text and element.text.strip():
                values[element.tag.rsplit("}", 1)[-1]] = element.text.strip()
        return values

    @staticmethod
    def _custom_values(archive: zipfile.ZipFile, name: str) -> dict[str, str]:
        try:
            root = ElementTree.fromstring(archive.read(name))
        except KeyError:
            return {}
        return {
            str(element.attrib["name"]): next((text.strip() for text in element.itertext() if text.strip()), "")
            for element in root.findall("{*}property")
            if element.attrib.get("name")
        }

    @staticmethod
    def _suffix(file_record: FileRecord, path: Path | None) -> str:
        return (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).casefold()

    @staticmethod
    def _field(
        identifier: str, label: str, value: str | int, order: int, category: MetadataCategory = MetadataCategory.OFFICE
    ) -> MetadataField:
        return MetadataField(
            identifier,
            category,
            label,
            value,
            source="builtin.office",
            confidence=MetadataConfidence.HIGH,
            display_order=order,
        )
