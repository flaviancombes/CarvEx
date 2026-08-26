"""Tests de l'instrumentation passive du retour de la boucle Qt."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from ui.ui_responsiveness_instrumentation import UiResponsivenessProbe
from utils import performance


def test_ui_probe_records_paints_event_loop_and_mouse_input(qapp, caplog, monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level(logging.INFO, logger="carvex.performance")
    main_window = QWidget()
    file_table = QWidget(main_window)
    timeline = QWidget(main_window)
    details = QWidget(main_window)
    progress = QWidget(main_window)
    for widget in (file_table, timeline, details, progress):
        widget.setGeometry(0, 0, 80, 50)
        widget.show()
    main_window.resize(200, 100)
    main_window.show()

    probe = UiResponsivenessProbe(main_window, file_table, timeline, details, progress)
    try:
        for widget in (main_window, file_table, timeline, details, progress):
            widget.update()
        qapp.processEvents()
        probe.mark_pipeline_finished()
        QTest.mouseClick(file_table, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        qapp.processEvents()

        assert "[UI] Premier processEvents utile" in caplog.text
        assert "[UI] Progression affichée 100 %" in caplog.text
        assert "[UI] Premier paint MainWindow" in caplog.text
        assert "[UI] Premier paint FileTable" in caplog.text
        assert "[UI] Premier paint Details" in caplog.text
        assert "[UI] Premier événement souris traité" in caplog.text
        assert "[UI] Fin pipeline métier" in caplog.text
    finally:
        probe.close()
        main_window.close()
