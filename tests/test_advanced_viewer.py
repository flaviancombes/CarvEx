from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPdfWriter

from ui.advanced_viewer import AdvancedViewer
from ui.preview_panel import PreviewPanel


def _write_image(path, color: Qt.GlobalColor = Qt.GlobalColor.red) -> None:
    image = QImage(1_200, 800, QImage.Format.Format_ARGB32)
    image.fill(color)
    assert image.save(str(path))


def _write_pdf(path) -> None:
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.drawText(100, 100, "CarvEx PDF")
    painter.end()


def test_image_viewer_opens_closes_and_supports_fit_and_actual_size(tmp_path, qtbot):
    path = tmp_path / "photo.png"
    _write_image(path)
    viewer = AdvancedViewer({"name": "photo.png", "mime": "image/png", "output": str(path)})
    qtbot.addWidget(viewer)

    viewer.show()
    qtbot.waitUntil(lambda: not viewer.image_canvas._item.pixmap().isNull())
    viewer.image_canvas.actual_size()
    viewer.image_canvas.fit_image()
    viewer.close()

    assert not viewer.isVisible()


def test_preview_panel_opens_the_independent_viewer_with_the_existing_image(tmp_path, qtbot):
    path = tmp_path / "photo.png"
    _write_image(path)
    panel = PreviewPanel()
    qtbot.addWidget(panel)

    panel.set_file({"name": "photo.png", "mime": "image/png", "output": str(path)})
    qtbot.waitUntil(lambda: panel._original_pixmap is not None)
    panel.open_viewer()

    assert panel._viewer is not None
    assert panel._viewer.isVisible()
    panel._viewer.close()


def test_text_viewer_loads_asynchronously_with_line_numbers_and_copy(tmp_path, qtbot):
    path = tmp_path / "notes.txt"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    viewer = AdvancedViewer({"name": "notes.txt", "mime": "text/plain", "output": str(path)})
    qtbot.addWidget(viewer)

    viewer.show()
    qtbot.waitUntil(lambda: viewer.text_editor.toPlainText().startswith("one"))
    viewer.text_editor.selectAll()
    viewer.text_editor.copy()

    assert viewer.text_editor.line_number_area_width() > 0


def test_pdf_viewer_opens_and_navigates_pages_without_blocking(tmp_path, qtbot):
    path = tmp_path / "sample.pdf"
    _write_pdf(path)
    viewer = AdvancedViewer({"name": "sample.pdf", "mime": "application/pdf", "output": str(path)})
    qtbot.addWidget(viewer)

    viewer.show()
    qtbot.waitUntil(lambda: viewer.pdf_document.pageCount() == 1)
    viewer._next_pdf_page()
    viewer._previous_pdf_page()

    assert viewer.pdf_pages.count() == 1


def test_corrupted_image_and_rapid_panel_changes_do_not_display_stale_preview(tmp_path, qtbot):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _write_image(first, Qt.GlobalColor.red)
    _write_image(second, Qt.GlobalColor.blue)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"invalid")

    viewer = AdvancedViewer({"name": "broken.png", "mime": "image/png", "output": str(broken)})
    qtbot.addWidget(viewer)
    viewer.show()
    qtbot.waitUntil(lambda: "corrompue" in viewer.status.text())

    panel = PreviewPanel()
    qtbot.addWidget(panel)
    panel.set_file({"mime": "image/png", "output": str(first)})
    panel.set_file({"mime": "image/png", "output": str(second)})
    qtbot.waitUntil(lambda: panel._original_pixmap is not None)

    assert panel._original_pixmap.toImage().pixelColor(0, 0) == Qt.GlobalColor.blue
