"""Extraction défensive de propriétés PE et ELF depuis leurs en-têtes."""

from __future__ import annotations

import math
import struct
from pathlib import Path

from metadata.base import BaseMetadataExtractor, FileRecord, MetadataCategory, MetadataConfidence, MetadataField


class ExecutableMetadataExtractor(BaseMetadataExtractor):
    provider_id = "builtin.executable"
    priority = 100
    _SUFFIXES = {".exe", ".dll", ".sys", ".msi", ".apk", ".elf", ".so"}

    def supports(self, file_record: FileRecord) -> bool:
        path = self.existing_path(file_record)
        return (
            str(file_record.get("category") or "") == "Executables" or self._suffix(file_record, path) in self._SUFFIXES
        )

    def extract(self, file_record: FileRecord) -> tuple[MetadataField, ...]:
        path = self.existing_path(file_record)
        if path is None:
            return ()
        try:
            data = path.read_bytes()
        except OSError:
            return ()
        try:
            if data.startswith(b"MZ"):
                return tuple(self._pe_fields(data))
            if data.startswith(b"\x7fELF"):
                return tuple(self._elf_fields(data))
        except (IndexError, struct.error, ValueError):
            return ()
        return ()

    def _pe_fields(self, data: bytes) -> list[MetadataField]:
        offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[offset : offset + 4] != b"PE\0\0":
            return []
        machine, sections, timestamp, _, _, optional_size, _ = struct.unpack_from("<HHIIIHH", data, offset + 4)
        fields = [
            self._field("executable.format", "Format", "PE", 10),
            self._field(
                "executable.architecture",
                "Architecture",
                {0x14C: "x86", 0x8664: "x64", 0xAA64: "ARM64"}.get(machine, hex(machine)),
                20,
            ),
            self._field("pe.compilation_timestamp", "Timestamp compilateur", timestamp, 30),
            self._field("pe.sections", "Sections", sections, 40),
        ]
        section_offset = offset + 24 + optional_size
        names: list[str] = []
        entropies: list[float] = []
        for index in range(sections):
            start = section_offset + index * 40
            name, raw_size, raw_offset = struct.unpack_from("<8s12xII", data, start)
            names.append(name.rstrip(b"\0").decode(errors="replace"))
            payload = data[raw_offset : raw_offset + raw_size]
            if payload:
                entropies.append(self._entropy(payload))
        if names:
            fields.append(self._field("pe.section_names", "Noms des sections", ", ".join(names), 50))
        if entropies:
            fields.append(
                self._field(
                    "pe.max_entropy", "Entropie maximale", f"{max(entropies):.2f}", 60, MetadataCategory.FORENSIC
                )
            )
        return fields

    def _elf_fields(self, data: bytes) -> list[MetadataField]:
        bitness = {1: "32 bits", 2: "64 bits"}.get(data[4], "inconnue")
        endianness = "little" if data[5] == 1 else "big" if data[5] == 2 else "little"
        endian = "<" if endianness == "little" else ">"
        machine = struct.unpack_from(f"{endian}H", data, 18)[0]
        return [
            self._field("executable.format", "Format", "ELF", 10),
            self._field(
                "executable.architecture",
                "Architecture",
                {3: "x86", 62: "x64", 183: "ARM64"}.get(machine, str(machine)),
                20,
            ),
            self._field("elf.bitness", "Architecture binaire", bitness, 30),
            self._field("elf.endianness", "Endianness", endianness, 40),
        ]

    @staticmethod
    def _entropy(data: bytes) -> float:
        length = len(data)
        return -sum(
            (count / length) * math.log2(count / length)
            for count in (data.count(bytes([item])) for item in range(256))
            if count
        )

    @staticmethod
    def _suffix(file_record: FileRecord, path: Path | None) -> str:
        return (path.suffix if path else Path(str(file_record.get("name") or "")).suffix).casefold()

    @staticmethod
    def _field(
        identifier: str,
        label: str,
        value: str | int,
        order: int,
        category: MetadataCategory = MetadataCategory.EXECUTABLE,
    ) -> MetadataField:
        return MetadataField(
            identifier,
            category,
            label,
            value,
            source="builtin.executable",
            confidence=MetadataConfidence.HIGH,
            display_order=order,
        )
