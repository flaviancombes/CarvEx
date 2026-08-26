"""Régressions du lecteur vidéo Qt intégré à l'aperçu."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaFormat, QMediaMetaData

from ui.preview_panel import MediaReadability, PreviewPanel, _PreviewResult


def test_qt_multimedia_backend_advertises_h264_decoding():
    codecs = QMediaFormat().supportedVideoCodecs(QMediaFormat.ConversionMode.Decode)

    assert QMediaFormat.VideoCodec.H264 in codecs


class _MediaMetadata:
    def __init__(self) -> None:
        self.requested_keys: list[QMediaMetaData.Key] = []

    def value(self, key: QMediaMetaData.Key):
        self.requested_keys.append(key)
        if key in {QMediaMetaData.Key.AudioCodec, QMediaMetaData.Key.VideoCodec}:
            raise RuntimeError("Can't find converter for codec enum")
        return 25 if key == QMediaMetaData.Key.VideoFrameRate else None


class _MediaPlayer:
    def __init__(self) -> None:
        self.stopped = False
        self.paused = False
        self._metadata = _MediaMetadata()

    def source(self) -> QUrl:
        return QUrl.fromLocalFile("C:/evidence/video.mp4")

    def duration(self) -> int:
        return 10_000

    def position(self) -> int:
        return 500

    def metaData(self) -> _MediaMetadata:  # noqa: N802
        return self._metadata

    def stop(self) -> None:
        self.stopped = True

    def pause(self) -> None:
        self.paused = True


def test_video_metadata_does_not_request_unconvertible_codec_enums(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    player = _MediaPlayer()
    panel._player = player
    panel._active_media_path = "C:/evidence/video.mp4"

    panel._update_media_details()

    assert QMediaMetaData.Key.VideoCodec not in player._metadata.requested_keys
    assert QMediaMetaData.Key.AudioCodec not in player._metadata.requested_keys
    assert "FPS : 25" in panel.details.text()


def test_video_player_error_is_rendered_as_user_facing_fallback(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    player = _MediaPlayer()
    panel._player = player
    panel._active_media_path = "C:/evidence/recovered.mp4"
    panel.video_widget.show()
    panel.play_button.show()

    panel._on_media_error()

    assert player.stopped
    assert panel._active_media_path is None
    assert not panel.video_widget.isVisible()
    assert not panel.play_button.isVisible()
    assert panel.media_readability is MediaReadability.UNREADABLE
    assert "illisible" in panel.description.text()


def test_clearing_the_panel_detaches_the_previous_media_source(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    panel._active_media_path = "C:/evidence/previous.mp4"

    panel.clear()

    assert panel._active_media_path is None
    assert panel._player.source().isEmpty()


def test_stale_video_result_is_ignored_after_a_file_change(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    stale_generation = panel._generation
    panel.clear()

    panel._on_preview_ready(
        stale_generation, "", _PreviewResult(None, "Vidéo", media_kind="video", media_path="old.mp4")
    )

    assert panel._active_media_path is None
    assert panel._player.source().isEmpty()


class _ValidFrame:
    @staticmethod
    def isValid() -> bool:  # noqa: N802
        return True


def test_video_error_after_a_valid_frame_is_partially_readable(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    player = _MediaPlayer()
    panel._player = player
    panel._active_media_path = "C:/evidence/partial.mp4"
    panel.show()
    panel.video_widget.show()

    panel._on_video_frame(panel._media_generation, _ValidFrame())
    panel._on_media_error()

    assert player.paused
    assert panel.media_readability is MediaReadability.PARTIALLY_READABLE
    assert panel.video_widget.isVisible()
    assert "partiellement lisible" in panel.description.text()


def test_end_before_the_last_frame_is_partially_readable(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    player = _MediaPlayer()
    panel._player = player
    panel._active_media_path = "C:/evidence/partial.mp4"
    panel._media_frame_received = True
    panel._last_frame_position = 0

    panel._finish_media_at_end()

    assert panel.media_readability is MediaReadability.PARTIALLY_READABLE


def test_end_after_a_final_frame_is_fully_readable(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    player = _MediaPlayer()
    panel._player = player
    panel._active_media_path = "C:/evidence/complete.mp4"
    panel._media_frame_received = True
    panel._last_frame_position = 10_000

    panel._finish_media_at_end()

    assert panel.media_readability is MediaReadability.FULLY_READABLE


def test_stale_media_error_cannot_change_the_current_source(qtbot):
    panel = PreviewPanel()
    qtbot.addWidget(panel)
    panel._active_media_path = "C:/evidence/current.mp4"
    panel._media_generation = 2

    panel._on_media_error(1)

    assert panel._active_media_path == "C:/evidence/current.mp4"
    assert panel.media_readability is None
