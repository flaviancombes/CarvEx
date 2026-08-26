"""Aperçus asynchrones et bornés du panneau de détails partagé."""

from __future__ import annotations

import tarfile
import zipfile
from collections import OrderedDict
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QToolButton, QVBoxLayout

from ui.preview_providers import (
    PreviewProvider,
    PreviewProviderRegistry,
    PreviewRequest,
    PreviewResult,
    build_default_preview_registry,
)
from ui.theme import Metrics

_PreviewResult = PreviewResult


class MediaReadability(Enum):
    FULLY_READABLE = "fully_readable"
    PARTIALLY_READABLE = "partially_readable"
    UNREADABLE = "unreadable"


class _PreviewCanvas(QLabel):
    activated = Signal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.activated.emit()
        event.accept()


class _PreviewCache:
    """Cache LRU borné des seules images décodées, sans pixmap hors UI."""

    def __init__(self, max_bytes: int = 64 * 1024 * 1024) -> None:
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, tuple[PreviewResult, int]] = OrderedDict()
        self._size_bytes = 0

    def get(self, key: str) -> PreviewResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry[0]

    def put(self, key: str, result: PreviewResult) -> None:
        if result.image is None or result.image.isNull():
            return
        image_size = result.image.sizeInBytes()
        if image_size > self._max_bytes:
            return
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._size_bytes -= previous[1]
        self._entries[key] = (result, image_size)
        self._size_bytes += image_size
        while self._size_bytes > self._max_bytes and self._entries:
            _key, (_result, discarded_size) = self._entries.popitem(last=False)
            self._size_bytes -= discarded_size


class _PreviewSignals(QObject):
    ready = Signal(int, str, object)


class _PreviewLoadTask(QRunnable):
    """Exécute le provider spécialisé hors du thread graphique."""

    def __init__(
        self,
        generation: int,
        cache_key: str,
        request: PreviewRequest,
        registry: PreviewProviderRegistry,
        signals: _PreviewSignals,
    ) -> None:
        super().__init__()
        self._generation = generation
        self._cache_key = cache_key
        self._request = request
        self._registry = registry
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._registry.resolve(self._request).load(self._request)
        except (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            UnicodeError,
            tarfile.TarError,
            zipfile.BadZipFile,
        ):
            result = PreviewResult(
                None, "Aperçu indisponible", body="Le contenu est corrompu, illisible ou non pris en charge."
            )
        self._signals.ready.emit(self._generation, self._cache_key, result)


class PreviewPanel(QFrame):
    """Centre d'inspection adaptatif alimenté par des providers enregistrés."""

    IMAGE_MIME_PREFIX = "image/"
    DECODE_SIZE = QSize(1400, 900)
    _image_cache = _PreviewCache()

    def __init__(self, parent=None, registry: PreviewProviderRegistry | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._registry = registry or build_default_preview_registry()
        self._original_pixmap: QPixmap | None = None
        self._file_record: Mapping[str, Any] | None = None
        self._active_media_path: str | None = None
        self._media_generation = 0
        self._media_signal_handlers: list[tuple[Any, Any]] = []
        self._media_frame_received = False
        self._last_frame_position = -1
        self._media_terminal = False
        self._media_readability: MediaReadability | None = None
        self._viewer = None
        self._generation = 0
        self._signals = _PreviewSignals(self)
        self._signals.ready.connect(self._on_preview_ready)
        self._thread_pool = QThreadPool.globalInstance()
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.timeout.connect(self._scale_pixmap)

        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING
        )
        layout.setSpacing(Metrics.PANEL_SPACING)
        self.heading = QLabel("APERÇU", self)
        layout.addWidget(self.heading)

        self.canvas = _PreviewCanvas(self)
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumHeight(Metrics.PREVIEW_MIN_HEIGHT)
        self.canvas.setWordWrap(True)
        self.canvas.activated.connect(self.open_viewer)
        layout.addWidget(self.canvas)

        self.viewer_button = QToolButton(self)
        self.viewer_button.setText("Ouvrir dans la visionneuse")
        self.viewer_button.clicked.connect(self.open_viewer)
        self.viewer_button.hide()
        layout.addWidget(self.viewer_button)

        self.video_widget = QVideoWidget(self)
        self.video_widget.setMinimumHeight(Metrics.PREVIEW_MIN_HEIGHT)
        self.video_widget.hide()
        self._player.setVideoOutput(self.video_widget)
        layout.addWidget(self.video_widget)

        self.play_button = QToolButton(self)
        self.play_button.setText("Lire")
        self.play_button.clicked.connect(self._toggle_media_playback)
        self.play_button.hide()
        layout.addWidget(self.play_button)

        self.description = QLabel(self)
        self.description.setWordWrap(True)
        self.description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.description)
        self.details = QLabel(self)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setWordWrap(True)
        self.details.hide()
        layout.addWidget(self.details)
        self.body = QPlainTextEdit(self)
        self.body.setReadOnly(True)
        self.body.setMaximumBlockCount(1_000)
        self.body.setMaximumHeight(180)
        self.body.hide()
        layout.addWidget(self.body)
        self.clear()

    def register_provider(self, provider: PreviewProvider) -> None:
        """Point d'extension explicite pour un format futur ou un module tiers."""
        self._registry.register(provider)

    def clear(self) -> None:
        self._generation += 1
        self._original_pixmap = None
        self._file_record = None
        self._scale_timer.stop()
        self._reset_media()
        self.canvas.clear()
        self.canvas.setText("▣")
        self.canvas.show()
        self.video_widget.hide()
        self.play_button.hide()
        self.viewer_button.hide()
        self.description.setText("Sélectionnez un fichier pour afficher son aperçu.")
        self.details.clear()
        self.details.hide()
        self.body.clear()
        self.body.hide()

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        if file_record is None:
            self.clear()
            return
        self._generation += 1
        self._original_pixmap = None
        self._file_record = file_record
        self._reset_media()
        self.video_widget.hide()
        self.play_button.hide()
        self.canvas.show()
        self.viewer_button.show()
        path = self._preview_path(file_record)
        mime = str(file_record.get("mime") or "").lower()
        request = PreviewRequest(file_record, path, mime, self.DECODE_SIZE)
        cache_key = self._cache_key(path, mime) if path is not None else ""
        cached = self._image_cache.get(cache_key) if cache_key else None
        if cached is not None:
            self._show_preview_result(cached)
            return
        self.canvas.clear()
        self.canvas.setText("Chargement de l’aperçu…")
        self.description.clear()
        self.details.hide()
        self.body.hide()
        self._thread_pool.start(_PreviewLoadTask(self._generation, cache_key, request, self._registry, self._signals))

    def open_viewer(self) -> None:
        """Ouvre une fenêtre autonome en réutilisant le résultat image P6 si présent."""
        if self._file_record is None:
            return
        from ui.advanced_viewer import AdvancedViewer

        path = self._preview_path(self._file_record)
        mime = str(self._file_record.get("mime") or "").lower()
        cached = self._image_cache.get(self._cache_key(path, mime)) if path is not None else None
        self._viewer = AdvancedViewer(
            self._file_record,
            parent=self.window(),
            registry=self._registry,
            initial_image=cached.image if cached is not None else None,
        )
        self._viewer.show()
        self._viewer.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._original_pixmap is not None:
            self._scale_timer.start(40)

    @staticmethod
    def _preview_path(file_record: Mapping[str, Any]) -> Path | None:
        for field in ("output", "source_path"):
            value = file_record.get(field)
            if value:
                path = Path(str(value))
                if path.is_file():
                    return path
        return None

    @staticmethod
    def _cache_key(path: Path, mime: str) -> str:
        stat = path.stat()
        return f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{mime}"

    def _on_preview_ready(self, generation: int, cache_key: str, result: PreviewResult) -> None:
        if generation != self._generation:
            return
        if cache_key and result.image is not None:
            self._image_cache.put(cache_key, result)
        self._show_preview_result(result)

    def _show_preview_result(self, result: PreviewResult) -> None:
        self._original_pixmap = QPixmap.fromImage(result.image) if result.image is not None else None
        if result.image is None:
            self.canvas.clear()
            self.canvas.setText("▣")
        self.description.setText(result.description)
        self._set_details(result.details)
        self.body.setPlainText(result.body)
        self.body.setVisible(bool(result.body))
        if result.media_kind is not None and result.media_path is not None:
            self._show_media(result.media_kind, result.media_path)
        if self._original_pixmap is not None:
            self._scale_pixmap()

    def _set_details(self, details: tuple[tuple[str, str], ...]) -> None:
        self.details.setText("\n".join(f"{name} : {value}" for name, value in details))
        self.details.setVisible(bool(details))

    def _show_media(self, kind: str, path: str) -> None:
        self._media_generation += 1
        generation = self._media_generation
        self._active_media_path = path
        self._media_frame_received = False
        self._last_frame_position = -1
        self._media_terminal = False
        self._media_readability = None
        self._connect_media_signals(generation)
        self._player.setSource(QUrl.fromLocalFile(path))
        self.canvas.setVisible(kind != "video")
        self.video_widget.setVisible(kind == "video")
        self.play_button.setText("Lire")
        self.play_button.show()

    def _toggle_media_playback(self) -> None:
        if self._active_media_path is None or self._media_terminal:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.play_button.setText("Lire")
        else:
            self._player.play()
            self.play_button.setText("Pause")

    @property
    def media_readability(self) -> MediaReadability | None:
        return self._media_readability

    def _update_media_details(self, generation: int | None = None) -> None:
        if generation is not None and generation != self._media_generation:
            return
        if self._active_media_path is None or self._player.source().isEmpty():
            return
        values = {
            line.partition(" : ")[0]: line.partition(" : ")[2]
            for line in self.details.text().splitlines()
            if " : " in line
        }
        duration = self._player.duration()
        if duration > 0:
            values["Durée"] = f"{duration / 1000:.2f} s"
        metadata = self._player.metaData()
        for key, label in (
            (QMediaMetaData.Key.VideoFrameRate, "FPS"),
            (QMediaMetaData.Key.Resolution, "Résolution"),
            (QMediaMetaData.Key.AudioBitRate, "Débit"),
            (QMediaMetaData.Key.VideoBitRate, "Débit vidéo"),
        ):
            try:
                value = metadata.value(key)
            except RuntimeError:
                continue
            if value not in (None, ""):
                values[label] = str(value)
        self.details.setText("\n".join(f"{name} : {value}" for name, value in values.items()))
        self.details.show()

    def _render_unreadable_media_error(self, *_args) -> None:
        """Présente les erreurs FFmpeg/backend attendues sans exception Qt brute."""
        if self._active_media_path is None:
            return
        self._player.stop()
        self._active_media_path = None
        self.video_widget.hide()
        self.play_button.hide()
        self.canvas.show()
        self.canvas.clear()
        self.canvas.setText("▣")
        self.description.setText(
            "Impossible de lire cette vidéo : fichier probablement corrompu ou format non pris en charge."
        )

    def _on_media_error(self, generation: int | None = None) -> None:
        if generation is not None and generation != self._media_generation:
            return
        if self._active_media_path is None or self._media_terminal:
            return
        self._finish_media_as_failed()

    def _on_media_status_changed(self, generation: int, status: QMediaPlayer.MediaStatus) -> None:
        if generation != self._media_generation or self._active_media_path is None or self._media_terminal:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._finish_media_as_failed()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._finish_media_at_end()

    def _on_video_frame(self, generation: int, frame) -> None:
        if generation != self._media_generation or self._active_media_path is None or self._media_terminal:
            return
        if not frame.isValid():
            return
        self._media_frame_received = True
        self._last_frame_position = self._player.position()

    def _finish_media_as_failed(self) -> None:
        self._media_terminal = True
        self.play_button.hide()
        if self._media_frame_received:
            self._media_readability = MediaReadability.PARTIALLY_READABLE
            self._player.pause()
            self.description.setText(
                "Vidéo partiellement lisible. Certaines données vidéo sont corrompues ou manquantes. "
                "La lecture s’arrête avant la fin du fichier."
            )
            return

        self._media_readability = MediaReadability.UNREADABLE
        self._render_unreadable_media_error()
        self.description.setText(
            "Vidéo illisible. Aucune image vidéo exploitable n’a pu être décodée. "
            "Le fichier peut être incomplet ou corrompu."
        )

    def _finish_media_at_end(self) -> None:
        duration = self._player.duration()
        tolerance = max(1_000, duration // 50)
        if not self._media_frame_received or (duration > 0 and self._last_frame_position < duration - tolerance):
            self._finish_media_as_failed()
            return
        self._media_terminal = True
        self._media_readability = MediaReadability.FULLY_READABLE
        self.play_button.setText("Lire")

    def _on_playback_state_changed(self, generation: int, state: QMediaPlayer.PlaybackState) -> None:
        if generation != self._media_generation or self._active_media_path is None or self._media_terminal:
            return
        self.play_button.setText("Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Lire")

    def _connect_media_signals(self, generation: int) -> None:
        self._disconnect_media_signals()
        handlers = (
            (self._player.durationChanged, lambda *_args: self._update_media_details(generation)),
            (self._player.metaDataChanged, lambda *_args: self._update_media_details(generation)),
            (self._player.errorOccurred, lambda *_args: self._on_media_error(generation)),
            (self._player.mediaStatusChanged, lambda status: self._on_media_status_changed(generation, status)),
            (
                self._player.playbackStateChanged,
                lambda state: self._on_playback_state_changed(generation, state),
            ),
            (self.video_widget.videoSink().videoFrameChanged, lambda frame: self._on_video_frame(generation, frame)),
        )
        for signal, handler in handlers:
            signal.connect(handler)
        self._media_signal_handlers = list(handlers)

    def _disconnect_media_signals(self) -> None:
        for signal, handler in self._media_signal_handlers:
            try:
                signal.disconnect(handler)
            except (RuntimeError, TypeError):
                pass
        self._media_signal_handlers.clear()

    def _reset_media(self) -> None:
        self._media_generation += 1
        self._disconnect_media_signals()
        self._active_media_path = None
        self._media_frame_received = False
        self._last_frame_position = -1
        self._media_terminal = False
        self._media_readability = None
        self._player.stop()
        self._player.setSource(QUrl())

    def _scale_pixmap(self) -> None:
        if self._original_pixmap is None:
            return
        size = self.canvas.size().boundedTo(QSize(700, 300))
        self.canvas.setPixmap(
            self._original_pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
