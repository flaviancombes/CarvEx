"""Pillow errors caused by damaged PhotoRec images are expected failures."""

from __future__ import annotations

import logging
from uuid import uuid4

from PIL import UnidentifiedImageError

from metadata.base import BaseMetadataExtractor, MetadataResult
from metadata.image import ImageMetadataExtractor
from metadata.manager import MetadataManager


class _FailingImageExtractor(BaseMetadataExtractor):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def supports(self, _file_record) -> bool:
        return True

    def extract(self, _file_record) -> MetadataResult:
        raise self._error


def test_corrupted_pillow_image_is_unavailable_without_traceback(caplog):
    manager = MetadataManager((_FailingImageExtractor(UnidentifiedImageError("cannot identify image file")),))

    with caplog.at_level(logging.DEBUG, logger="metadata.manager"):
        result = manager.extract({"file_id": str(uuid4()), "name": "broken.jpg"})

    assert result.unavailable_message is not None
    records = [record for record in caplog.records if record.name == "metadata.manager"]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert records[0].exc_info is None


def test_invalid_recovered_jpeg_uses_the_expected_pillow_path(tmp_path, caplog):
    image_path = tmp_path / "recovered.jpg"
    image_path.write_bytes(b"not a valid image")
    manager = MetadataManager((ImageMetadataExtractor(),))

    with caplog.at_level(logging.DEBUG, logger="metadata.manager"):
        result = manager.extract({"file_id": str(uuid4()), "name": image_path.name, "output": str(image_path)})

    assert result.unavailable_message is not None
    assert any(record.levelno == logging.DEBUG and record.exc_info is None for record in caplog.records)


def test_known_pillow_stream_errors_are_expected_metadata_unavailability(caplog):
    manager = MetadataManager((_FailingImageExtractor(OSError("broken data stream when reading image file")),))

    with caplog.at_level(logging.DEBUG, logger="metadata.manager"):
        result = manager.extract({"file_id": str(uuid4()), "name": "broken.jpg"})

    assert result.unavailable_message is not None
    assert any(record.levelno == logging.DEBUG and record.exc_info is None for record in caplog.records)


def test_unexpected_metadata_error_remains_logged_with_traceback(caplog):
    manager = MetadataManager((_FailingImageExtractor(RuntimeError("unexpected parser failure")),))

    with caplog.at_level(logging.ERROR, logger="metadata.manager"):
        result = manager.extract({"file_id": str(uuid4()), "name": "image.jpg"})

    assert result.unavailable_message is not None
    assert any(record.levelno == logging.ERROR and record.exc_info is not None for record in caplog.records)
