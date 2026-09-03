"""Instrumentation opt-in du retour effectif de l'interface Qt.

Ce module n'est actif que lorsque ``CARVEX_PERF=1``. Il observe les
événements Qt sans les accepter ni modifier leur ordre afin de mesurer le
temps entre la progression affichée à 100 % et la réactivité de l'interface.
"""

from __future__ import annotations

from time import perf_counter

from PySide6.QtCore import QAbstractEventDispatcher, QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from utils import performance


class UiResponsivenessProbe(QObject):
    """Observe passivement les premiers tours de boucle et peintures Qt."""

    _PAINT_LABELS = (
        ("Premier paint MainWindow", "main_window"),
        ("Premier paint FileTable", "file_table"),
        ("Premier paint Timeline", "timeline"),
        ("Premier paint Details", "details"),
    )

    def __init__(
        self,
        main_window: QWidget,
        file_table: QWidget,
        timeline: QWidget,
        details: QWidget,
        progress: QWidget,
    ) -> None:
        super().__init__(main_window)
        self._last_mark_at = perf_counter()
        self._application = QApplication.instance()
        self._widgets = {
            "main_window": main_window,
            "file_table": file_table,
            "timeline": timeline,
            "details": details,
            "progress": progress,
        }
        self._required_paints = {
            key for key in ("main_window", "file_table", "details") if self._widgets[key].isVisible()
        }
        if timeline.isVisible():
            self._required_paints.add("timeline")
        self._painted: set[str] = set()
        self._marks: set[str] = set()
        self._first_event_loop_turn = False
        self._interactive = False
        self._closed = False
        self._batch_started_at: float | None = None
        self._dispatcher = QAbstractEventDispatcher.instance()
        if self._application is not None:
            self._application.installEventFilter(self)
        if self._dispatcher is not None:
            self._dispatcher.awake.connect(self._on_event_loop_awake)
            self._dispatcher.aboutToBlock.connect(self._on_event_loop_about_to_block)
        QTimer.singleShot(0, self._mark_first_event_loop_turn)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Mesure les événements observés sans jamais les consommer."""
        if self._closed:
            return False
        if event.type() == QEvent.Type.Paint:
            self._mark_paint(watched)
            if self._is_watched_widget(watched, "progress"):
                self.mark_progress_displayed()
        elif event.type() == QEvent.Type.MouseButtonPress:
            self._mark_mouse_event(watched)
        return False

    def mark_progress_displayed(self) -> None:
        self._mark("Progression affichée 100 %")

    def mark_pipeline_finished(self) -> None:
        self._mark("Fin pipeline métier")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._application is not None:
            self._application.removeEventFilter(self)
        if self._dispatcher is not None:
            self._dispatcher.awake.disconnect(self._on_event_loop_awake)
            self._dispatcher.aboutToBlock.disconnect(self._on_event_loop_about_to_block)

    def _mark_paint(self, watched: QObject) -> None:
        for label, key in self._PAINT_LABELS:
            if key in self._painted or not self._is_watched_widget(watched, key):
                continue
            self._painted.add(key)
            self._mark(label)
            self._maybe_mark_interactive()
            return

    def _mark_mouse_event(self, watched: QObject) -> None:
        if any(self._is_watched_widget(watched, key) for key in self._widgets):
            self._mark("Premier événement souris traité")

    def _mark_first_event_loop_turn(self) -> None:
        if self._closed:
            return
        self._first_event_loop_turn = True
        self._mark("Premier processEvents utile")
        self._maybe_mark_interactive()

    def _on_event_loop_awake(self) -> None:
        self._batch_started_at = perf_counter()

    def _on_event_loop_about_to_block(self) -> None:
        if self._batch_started_at is None:
            return
        duration_ms = (perf_counter() - self._batch_started_at) * 1000
        self._batch_started_at = None
        if duration_ms > 100:
            self._log("Traitement thread UI >100 ms", duration_ms)

    def _is_watched_widget(self, watched: QObject, key: str) -> bool:
        widget = self._widgets[key]
        return watched is widget or (isinstance(watched, QWidget) and widget.isAncestorOf(watched))

    def _maybe_mark_interactive(self) -> None:
        if self._interactive or not self._first_event_loop_turn or not self._required_paints.issubset(self._painted):
            return
        self._interactive = True
        QTimer.singleShot(0, lambda: self._mark("Interface interactive"))

    def _mark(self, label: str) -> None:
        if label in self._marks or self._closed:
            return
        self._marks.add(label)
        now = perf_counter()
        self._log(label, (now - self._last_mark_at) * 1000)
        self._last_mark_at = now

    @staticmethod
    def _format_duration(duration_ms: float) -> str:
        milliseconds = max(0, round(duration_ms))
        minutes, milliseconds = divmod(milliseconds, 60_000)
        seconds, milliseconds = divmod(milliseconds, 1_000)
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _log(self, label: str, duration_ms: float) -> None:
        if performance.ENABLED:
            performance.LOGGER.info("[UI] %-32s %s", label, self._format_duration(duration_ms))


_active_probe: UiResponsivenessProbe | None = None


class UiEventLoopMonitor(QObject):
    """Détecte les tours de boucle Qt retardés et les relie aux opérations récentes."""

    def __init__(self, parent: QWidget, interval_ms: int = 100, threshold_ms: int = 150) -> None:
        super().__init__(parent)
        self._application = QApplication.instance()
        self._interval_ms = interval_ms
        self._threshold_ms = threshold_ms
        self._last_tick = perf_counter()
        self._last_event = "unknown"
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)
        if self._application is not None:
            self._application.installEventFilter(self)
        self._timer.start()

    def eventFilter(self, _watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if not self._closed:
            self._last_event = event.type().name
        return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        if self._application is not None:
            self._application.removeEventFilter(self)

    def _on_tick(self) -> None:
        now = perf_counter()
        elapsed_ms = (now - self._last_tick) * 1000
        self._last_tick = now
        if elapsed_ms <= self._interval_ms + self._threshold_ms:
            return
        recent = performance.recent_operations()
        context = (
            "; ".join(
                f"{entry.component}.{entry.operation}={entry.duration_ms:.1f}ms/{entry.thread_name}"
                for entry in recent[-5:]
            )
            or "none"
        )
        performance.LOGGER.warning(
            "[UI] EVENT LOOP STARVATION duration_ms=%.2f last_event=%s recent_operations=%s",
            elapsed_ms,
            self._last_event,
            context,
        )


_global_monitor: UiEventLoopMonitor | None = None


def start_global_ui_event_loop_monitor(main_window: QWidget) -> None:
    """Installe l'observateur global seulement lorsque CARVEX_PERF est actif."""
    global _global_monitor
    if not performance.ENABLED or _global_monitor is not None:
        return
    _global_monitor = UiEventLoopMonitor(main_window)


def stop_global_ui_event_loop_monitor() -> None:
    """Libère les hooks Qt installés pour le diagnostic global."""
    global _global_monitor
    if _global_monitor is not None:
        _global_monitor.close()
        _global_monitor = None


def start_ui_responsiveness_probe(progress_widget: QWidget, main_window: QWidget) -> None:
    """Démarre une mesure à l'instant où le dialogue d'import atteint 100 %."""
    global _active_probe
    if not performance.ENABLED:
        return
    if _active_probe is not None:
        _active_probe.close()
    file_table = getattr(main_window, "file_table", None)
    timeline = getattr(main_window, "timeline_view", None)
    details = getattr(main_window, "details_panel", None)
    if not all(isinstance(widget, QWidget) for widget in (file_table, timeline, details)):
        return
    _active_probe = UiResponsivenessProbe(main_window, file_table.view, timeline.table, details, progress_widget)


def mark_pipeline_finished() -> None:
    """Marque la fin de la phase métier sans modifier son exécution."""
    if _active_probe is not None:
        _active_probe.mark_pipeline_finished()


def stop_ui_responsiveness_probe() -> None:
    """Détache l'observateur à la fermeture du projet ou du dialogue."""
    global _active_probe
    if _active_probe is not None:
        _active_probe.close()
        _active_probe = None
