"""Corpus synthétique des métadonnées d'image typées et normalisées."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from PIL import Image, IptcImagePlugin, PngImagePlugin, UnidentifiedImageError

from metadata.base import MetadataValueType
from metadata.image import ImageMetadataExtractor


def _record(path, mime: str = "image/jpeg"):
    return {"file_id": str(uuid4()), "name": path.name, "output": str(path), "mime": mime}


def _fields(path, mime: str = "image/jpeg"):
    return {field.identifier: field for field in ImageMetadataExtractor().extract(_record(path, mime))}


def test_jpeg_extracts_typed_general_and_exif_values(tmp_path):
    path = tmp_path / "evidence.jpg"
    exif = Image.Exif()
    exif[271] = "Canon"
    exif[272] = "EOS R6"
    exif[274] = 6
    exif[306] = "2024:02:03 04:05:06"
    exif[34855] = 400
    Image.new("RGB", (40, 20), "red").save(path, exif=exif, dpi=(300, 300))

    fields = _fields(path)

    assert fields["image.width"].value == 40
    assert fields["image.width"].value_type is MetadataValueType.INTEGER
    assert fields["image.bits_per_pixel"].value == 24
    assert fields["image.dpi_x"].value_type is MetadataValueType.DECIMAL
    assert fields["exif.make"].value == "Canon"
    assert fields["exif.orientation"].value == 6
    assert fields["exif.datetime_modified"].value == datetime(
        2024, 2, 3, 4, 5, 6, tzinfo=fields["exif.datetime_modified"].value.tzinfo
    )


def test_png_text_gamma_and_icc_fields_are_indexable(tmp_path):
    path = tmp_path / "evidence.png"
    text = PngImagePlugin.PngInfo()
    text.add_text("Author", "Alice")
    Image.new("RGB", (8, 6), "blue").save(path, pnginfo=text, gamma=0.45455, icc_profile=b"icc profile")

    fields = _fields(path, "image/png")

    assert fields["png.text.author"].value == "Alice"
    assert fields["image.icc_profile.size"].value == len(b"icc profile")
    assert fields["image.icc_profile.sha256"].value_type is MetadataValueType.TEXT


@pytest.mark.parametrize(("suffix", "format_name"), ((".tiff", "TIFF"), (".gif", "GIF"), (".bmp", "BMP")))
def test_common_image_formats_have_typed_general_metadata(tmp_path, suffix, format_name):
    path = tmp_path / f"evidence{suffix}"
    kwargs = {"format": format_name}
    if format_name == "GIF":
        kwargs["comment"] = b"synthetic"
    Image.new("RGB", (12, 7), "green").save(path, **kwargs)

    fields = _fields(path, f"image/{format_name.casefold()}")

    assert fields["image.width"].value == 12
    assert fields["image.height"].value == 7
    assert fields["image.format"].value == format_name
    if format_name == "GIF":
        assert fields["gif.comment"].value == "synthetic"


def test_gps_is_stored_as_floats_and_gps_time_is_utc_aware():
    class _Exif:
        def get_ifd(self, _identifier):
            return {
                1: "N",
                2: ((48, 1), (51, 1), (0, 1)),
                3: "E",
                4: ((2, 1), (21, 1), (0, 1)),
                5: 0,
                6: (35, 1),
                7: ((10, 1), (20, 1), (30, 1)),
                11: (4, 1),
                12: "K",
                13: (80, 1),
                17: (90, 1),
                29: "2024:02:03",
                31: (3, 1),
            }

    fields = {field.identifier: field for field in ImageMetadataExtractor()._gps_fields(_Exif())}

    assert fields["exif.gps.latitude"].value == pytest.approx(48.85)
    assert fields["exif.gps.longitude"].value == pytest.approx(2.35)
    assert fields["exif.gps.altitude"].value == 35.0
    assert fields["exif.gps.speed"].value == 80.0
    assert fields["exif.gps.timestamp"].value.tzinfo is not None


def test_xmp_dates_are_timezone_aware_and_lightroom_values_are_retained():
    raw = b"""
    <x:xmpmeta xmlns:x='adobe:ns:meta/' xmlns:xmp='http://ns.adobe.com/xap/1.0/'
      xmlns:crs='http://ns.adobe.com/camera-raw-settings/1.0/'>
      <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns/'>
        <rdf:Description xmp:CreateDate='2024-02-03T04:05:06+02:00' crs:Version='13.0'/>
      </rdf:RDF>
    </x:xmpmeta>
    """

    fields = {field.identifier: field for field in ImageMetadataExtractor()._xmp_fields(raw)}

    assert fields["xmp.xmp.createdate"].value.tzinfo is not None
    assert fields["xmp.crs.version"].value == "13.0"


def test_iptc_is_semantic_and_preserves_keywords(monkeypatch):
    image = Image.new("RGB", (1, 1))
    monkeypatch.setattr(
        IptcImagePlugin,
        "getiptcinfo",
        lambda _image: {(2, 25): [b"forensic", b"photo"], (2, 80): b"Alice", (2, 55): b"20240203"},
    )

    fields = {field.identifier: field for field in ImageMetadataExtractor()._iptc_fields(image)}

    assert fields["iptc.keywords"].value == "forensic, photo"
    assert fields["iptc.author"].value == "Alice"
    assert fields["iptc.date_created"].value.tzinfo is not None


def test_heic_and_raw_names_are_accepted_when_a_decoder_is_available(tmp_path):
    extractor = ImageMetadataExtractor()
    heic_record = {"name": "mobile.heic", "mime": "image/heic"}
    raw_record = {"name": "camera.nef", "mime": ""}
    raw_like = tmp_path / "synthetic.dng"
    Image.new("RGB", (3, 2)).save(raw_like, format="TIFF")

    assert extractor.supports(heic_record)
    assert extractor.supports(raw_record)
    assert _fields(raw_like, "image/x-adobe-dng")["image.width"].value == 3


def test_images_without_exif_and_corrupted_images_are_safe(tmp_path):
    no_exif = tmp_path / "plain.jpg"
    broken = tmp_path / "broken.jpg"
    Image.new("RGB", (2, 2)).save(no_exif)
    broken.write_bytes(b"not an image")

    assert "exif.make" not in _fields(no_exif)
    with pytest.raises(UnidentifiedImageError):
        ImageMetadataExtractor().extract(_record(broken))
