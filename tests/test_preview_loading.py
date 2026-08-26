"""Regression tests for deferred and bounded detail previews."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from ui.preview_panel import PreviewPanel, _PreviewCache, _PreviewResult


def _write_image(path, width: int = 320, height: int = 200) -> None:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(path))


def test_image_preview_loads_deferred_and_updates_the_panel(tmp_path, qtbot):
    image_path = tmp_path / "large.png"
    _write_image(image_path, 2_000, 1_200)
    panel = PreviewPanel()
    qtbot.addWidget(panel)

    panel.set_file({"mime": "image/png", "output": str(image_path)})

    assert panel.canvas.text() == "Chargement de l’aperçu…"
    qtbot.waitUntil(lambda: panel._original_pixmap is not None)
    assert panel._original_pixmap.width() <= PreviewPanel.DECODE_SIZE.width()
    assert panel.description.text() == "Image — image/png"


def test_preview_cache_is_bounded_by_decoded_image_bytes():
    cache = _PreviewCache(max_bytes=15)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.blue)

    cache.put("too-large", _PreviewResult(image, "Image"))

    assert cache.get("too-large") is None


def test_decoded_preview_is_reused_without_starting_another_load(tmp_path, qtbot, monkeypatch):
    image_path = tmp_path / "cached.png"
    _write_image(image_path)
    monkeypatch.setattr(PreviewPanel, "_image_cache", _PreviewCache())
    record = {"mime": "image/png", "output": str(image_path)}

    first = PreviewPanel()
    qtbot.addWidget(first)
    first.set_file(record)
    qtbot.waitUntil(lambda: first._original_pixmap is not None)

    second = PreviewPanel()
    qtbot.addWidget(second)
    second.set_file(record)

    assert second._original_pixmap is not None


def test_invalid_pdf_keeps_the_gui_responsive_and_shows_a_fallback(tmp_path, qtbot):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not a valid pdf")
    panel = PreviewPanel()
    qtbot.addWidget(panel)

    panel.set_file({"mime": "application/pdf", "output": str(pdf_path)})

    assert panel.canvas.text() == "Chargement de l’aperçu…"
    qtbot.waitUntil(lambda: "Document PDF" in panel.description.text())
    assert panel._original_pixmap is None
