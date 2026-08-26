"""Fenêtre de consultation approfondie, indépendante du panneau de détails."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPointF, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSlider,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.preview_providers import PreviewProviderRegistry, build_default_preview_registry


class _ImageSignals(QObject):
    ready = Signal(int, object)


class _ImageLoadTask(QRunnable):
    """Décode l'image du viewer hors UI, avec une limite mémoire raisonnable."""

    MAX_DIMENSION = 8_000

    def __init__(self, generation: int, path: Path, signals: _ImageSignals) -> None:
        super().__init__()
        self._generation = generation
        self._path = path
        self._signals = signals

    def run(self) -> None:
        image = QImage()
        try:
            reader = QImageReader(str(self._path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > self.MAX_DIMENSION:
                reader.setScaledSize(
                    size.scaled(self.MAX_DIMENSION, self.MAX_DIMENSION, Qt.AspectRatioMode.KeepAspectRatio)
                )
            image = reader.read()
        except (OSError, RuntimeError, ValueError):
            image = QImage()
        try:
            self._signals.ready.emit(self._generation, image if not image.isNull() else None)
        except RuntimeError:
            # La fenêtre a été fermée avant la fin du décodage : résultat obsolète.
            return


class _TextSignals(QObject):
    ready = Signal(int, str, str)


class _TextLoadTask(QRunnable):
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, generation: int, path: Path, signals: _TextSignals) -> None:
        super().__init__()
        self._generation = generation
        self._path = path
        self._signals = signals

    def run(self) -> None:
        try:
            with self._path.open("rb") as source:
                data = source.read(self.MAX_BYTES)
            encoding = "utf-8"
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                encoding = "latin-1"
                text = data.decode(encoding, errors="replace")
        except OSError:
            text, encoding = "", "inconnu"
        try:
            self._signals.ready.emit(self._generation, text, encoding)
        except RuntimeError:
            return


class _PdfThumbnailSignals(QObject):
    ready = Signal(int, int, object)


class _PdfThumbnailTask(QRunnable):
    """Rend au plus cent miniatures PDF hors thread UI, sans cache parallèle."""

    MAX_THUMBNAILS = 100

    def __init__(self, generation: int, path: Path, signals: _PdfThumbnailSignals) -> None:
        super().__init__()
        self._generation = generation
        self._path = path
        self._signals = signals

    def run(self) -> None:
        document = QPdfDocument()
        try:
            document.load(str(self._path))
            for page in range(min(document.pageCount(), self.MAX_THUMBNAILS)):
                image = document.render(page, QSize(100, 140))
                if not image.isNull():
                    try:
                        self._signals.ready.emit(self._generation, page, image)
                    except RuntimeError:
                        return
        except (OSError, RuntimeError, ValueError):
            return


class ImageCanvas(QGraphicsView):
    """Canvas d'image avec zoom sous la molette et déplacement main libre."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def set_image(self, image: QImage) -> None:
        self._item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(self._item.boundingRect())
        self.fit_image()

    def fit_image(self) -> None:
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self) -> None:
        self.resetTransform()

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.scale(factor, factor)


class _LineNumberArea(QWidget):
    def __init__(self, editor, parent=None) -> None:
        super().__init__(parent or editor)
        self._editor = editor

    def sizeHint(self):  # noqa: N802
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_line_numbers(event)


class LineNumberTextEdit(QPlainTextEdit):
    """Éditeur lecture seule avec copie, retour à la ligne et numéros de lignes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(lambda _count: self._update_line_number_margin())
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_margin()

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 8 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_margin(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_margin()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_number_area.setGeometry(
            contents.left(), contents.top(), self.line_number_area_width(), contents.height()
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#252526"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#BFBFBF"))
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            number += 1


class AdvancedViewer(QDialog):
    """Visionneuse dédiée ; elle possède son état, mais pas de cache concurrent."""

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

    def __init__(
        self,
        file_record: Mapping[str, Any],
        parent=None,
        registry: PreviewProviderRegistry | None = None,
        initial_image: QImage | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Visionneuse — {file_record.get('name') or 'Sans nom'}")
        self.resize(1_100, 760)
        self._record = file_record
        self._path = self._resolve_path(file_record)
        self._mime = str(file_record.get("mime") or "").lower()
        self._registry = registry or build_default_preview_registry()
        self._initial_image = initial_image
        self._generation = 0
        self._thread_pool = QThreadPool.globalInstance()
        self._image_signals = _ImageSignals(self)
        self._image_signals.ready.connect(self._on_image_ready)
        self._text_signals = _TextSignals(self)
        self._text_signals.ready.connect(self._on_text_ready)
        self._thumbnail_signals = _PdfThumbnailSignals(self)
        self._thumbnail_signals.ready.connect(self._on_pdf_thumbnail_ready)
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.metaDataChanged.connect(self._show_media_information)

        layout = QVBoxLayout(self)
        self.toolbar = QToolBar(self)
        layout.addWidget(self.toolbar)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.content = QWidget(self)
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.content, 1)
        self._build_content()
        self._load()

    @staticmethod
    def _resolve_path(record: Mapping[str, Any]) -> Path | None:
        for field in ("output", "source_path"):
            value = record.get(field)
            if value:
                path = Path(str(value))
                if path.is_file():
                    return path
        return None

    def _build_content(self) -> None:
        self.image_canvas = ImageCanvas(self.content)
        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView(self.content)
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_pages = QListWidget(self.content)
        self.pdf_pages.currentRowChanged.connect(self._go_to_pdf_page)
        self.pdf_search = QLineEdit(self.content)
        self.pdf_search.setPlaceholderText("Rechercher dans le PDF…")
        self.pdf_search.textChanged.connect(self._search_pdf)
        self.pdf_search_model = QPdfSearchModel(self)
        self.pdf_search_model.setDocument(self.pdf_document)
        self.pdf_view.setSearchModel(self.pdf_search_model)
        self.text_editor = LineNumberTextEdit(self.content)
        self.text_editor.setReadOnly(True)
        self.text_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.media_widget = QVideoWidget(self.content)
        self._player.setVideoOutput(self.media_widget)
        self.media_slider = QSlider(Qt.Orientation.Horizontal, self.content)
        self.media_slider.sliderMoved.connect(self._player.setPosition)
        self.media_play = QToolButton(self.content)
        self.media_play.setText("Lire")
        self.media_play.clicked.connect(self._toggle_playback)
        self.media_capture = QToolButton(self.content)
        self.media_capture.setText("Capturer l'image")
        self.media_capture.clicked.connect(self._capture_video_frame)

        self._set_content(self.text_editor)

    def _load(self) -> None:
        self._generation += 1
        if self._path is None:
            self.status.setText("Le fichier n'est plus disponible sur le disque.")
            return
        if self._mime.startswith("image/"):
            self._load_image()
        elif self._mime == "application/pdf":
            self._load_pdf()
        elif self._mime.startswith("audio/") or self._mime.startswith("video/"):
            self._load_media()
        elif self._mime.startswith("text/") or self._path.suffix.lower() in self.TEXT_SUFFIXES:
            self._load_text()
        else:
            self.status.setText(
                "Ce format ne possède pas de visionneuse avancée. Les informations restent disponibles dans l'aperçu."
            )

    def _set_content(self, widget: QWidget) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
        self._content_layout.addWidget(widget)
        widget.show()

    def _load_image(self) -> None:
        self.status.setText("Chargement de l'image…")
        self._set_content(self.image_canvas)
        self._add_image_actions()
        if self._initial_image is not None:
            self.image_canvas.set_image(self._initial_image)
        self._thread_pool.start(_ImageLoadTask(self._generation, self._path, self._image_signals))

    def _on_image_ready(self, generation: int, image: QImage | None) -> None:
        if generation != self._generation:
            return
        if image is None:
            self.status.setText("Image corrompue ou format non pris en charge.")
            return
        self.image_canvas.set_image(image)
        self.status.setText(f"Image {image.width()} × {image.height()} px")

    def _add_image_actions(self) -> None:
        self.toolbar.clear()
        self.toolbar.addAction("Ajuster", self.image_canvas.fit_image)
        self.toolbar.addAction("100 %", self.image_canvas.actual_size)
        self.toolbar.addAction("Plein écran", self._toggle_full_screen)

    def _load_pdf(self) -> None:
        self.toolbar.clear()
        self.toolbar.addAction("Page précédente", self._previous_pdf_page)
        self.toolbar.addAction("Page suivante", self._next_pdf_page)
        self.toolbar.addAction("Zoom +", self._pdf_zoom_in)
        self.toolbar.addAction("Zoom −", self._pdf_zoom_out)
        self.toolbar.addAction("Plein écran", self._toggle_full_screen)
        self.pdf_document.load(str(self._path))
        if self.pdf_document.pageCount() <= 0:
            self.status.setText("PDF corrompu ou illisible.")
            return
        self.pdf_pages.clear()
        for page in range(self.pdf_document.pageCount()):
            self.pdf_pages.addItem(QListWidgetItem(f"Page {page + 1}"))
        self.pdf_pages.setCurrentRow(0)
        side = QWidget(self.content)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.pdf_search)
        side_layout.addWidget(self.pdf_pages)
        splitter = QSplitter(Qt.Orientation.Horizontal, self.content)
        splitter.addWidget(side)
        splitter.addWidget(self.pdf_view)
        splitter.setStretchFactor(1, 1)
        self._set_content(splitter)
        self.status.setText(f"PDF — {self.pdf_document.pageCount()} page(s)")
        self._thread_pool.start(_PdfThumbnailTask(self._generation, self._path, self._thumbnail_signals))

    def _on_pdf_thumbnail_ready(self, generation: int, page: int, image: QImage) -> None:
        if generation != self._generation or page >= self.pdf_pages.count():
            return
        item = self.pdf_pages.item(page)
        if item is not None:
            item.setIcon(QIcon(QPixmap.fromImage(image)))

    def _go_to_pdf_page(self, page: int) -> None:
        if page >= 0:
            self.pdf_view.pageNavigator().jump(page, QPointF(), 0)

    def _previous_pdf_page(self) -> None:
        self._go_to_pdf_page(max(0, self.pdf_view.pageNavigator().currentPage() - 1))

    def _next_pdf_page(self) -> None:
        self._go_to_pdf_page(min(self.pdf_document.pageCount() - 1, self.pdf_view.pageNavigator().currentPage() + 1))

    def _pdf_zoom_in(self) -> None:
        self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() * 1.25)

    def _pdf_zoom_out(self) -> None:
        self.pdf_view.setZoomFactor(self.pdf_view.zoomFactor() / 1.25)

    def _search_pdf(self, text: str) -> None:
        self.pdf_search_model.setSearchString(text)

    def _load_media(self) -> None:
        self.toolbar.clear()
        self.toolbar.addAction("Plein écran", self._toggle_full_screen)
        self._player.setSource(QUrl.fromLocalFile(str(self._path)))
        controls = QWidget(self.content)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(self.media_play)
        controls_layout.addWidget(self.media_slider, 1)
        if self._mime.startswith("video/"):
            controls_layout.addWidget(self.media_capture)
            container = QWidget(self.content)
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.addWidget(self.media_widget, 1)
            container_layout.addWidget(controls)
            self._set_content(container)
        else:
            self._set_content(controls)
        self.status.setText(f"{'Vidéo' if self._mime.startswith('video/') else 'Audio'} — {self._mime}")

    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.media_play.setText("Lire")
        else:
            self._player.play()
            self.media_play.setText("Pause")

    def _on_position_changed(self, position: int) -> None:
        if not self.media_slider.isSliderDown():
            self.media_slider.setValue(position)

    def _on_duration_changed(self, duration: int) -> None:
        self.media_slider.setRange(0, max(duration, 0))
        self._show_media_information()

    def _show_media_information(self) -> None:
        duration = self._player.duration()
        if duration > 0:
            self.status.setText(f"{self._mime} — {duration / 1000:.2f} s")

    def _capture_video_frame(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self, "Enregistrer la capture", "capture.png", "Images PNG (*.png)"
        )
        if path:
            self.capture_frame(Path(path))

    def capture_frame(self, path: Path) -> bool:
        """Capture le rendu vidéo courant sans interroger ou modifier le domaine."""
        pixmap = self.media_widget.grab()
        if pixmap.isNull():
            return False
        return pixmap.save(str(path), "PNG")

    def _load_text(self) -> None:
        self.toolbar.clear()
        find = QLineEdit(self)
        find.setPlaceholderText("Rechercher…")
        find.textChanged.connect(lambda text: self.text_editor.find(text))
        wrap = QAction("Retour à la ligne", self, checkable=True, checked=True)
        wrap.toggled.connect(
            lambda enabled: self.text_editor.setLineWrapMode(
                QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap
            )
        )
        self.toolbar.addWidget(find)
        self.toolbar.addAction(wrap)
        self.toolbar.addAction("Copier", self.text_editor.copy)
        self.toolbar.addAction("Plein écran", self._toggle_full_screen)
        self._set_content(self.text_editor)
        self.status.setText("Chargement du texte…")
        self._thread_pool.start(_TextLoadTask(self._generation, self._path, self._text_signals))

    def _on_text_ready(self, generation: int, text: str, encoding: str) -> None:
        if generation != self._generation:
            return
        self.text_editor.setPlainText(text)
        self.status.setText(f"Texte — {encoding} — {self.text_editor.blockCount()} ligne(s), limité à 8 MiB")

    def _toggle_full_screen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._generation += 1
        self._player.stop()
        super().closeEvent(event)
