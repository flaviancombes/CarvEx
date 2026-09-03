"""Tests de l'instrumentation globale des occupations du thread UI."""

from __future__ import annotations

import logging
from time import sleep

from PySide6.QtWidgets import QWidget

from ui.ui_responsiveness_instrumentation import UiEventLoopMonitor
from utils import performance


def test_operation_instrumentation_is_inactive_without_perf(caplog, monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", False)

    with performance.operation("FileTable", "category_filter"):
        pass

    assert not performance.recent_operations()
    assert not caplog.records


def test_operation_instrumentation_reports_threshold_thread_and_nesting(caplog, monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level(logging.INFO, logger="carvex.performance")

    with performance.operation("FileTable", "category_filter"):
        with performance.operation("FileFilterProxy", "apply"):
            sleep(0.11)

    entries = performance.recent_operations()
    assert entries[-1].thread_name == "MainThread"
    assert entries[-2].depth == 1
    assert entries[-1].depth == 0
    assert "[UI] BLOCK >100ms" in caplog.text
    assert "operation=FileFilterProxy.apply" in caplog.text


def test_event_loop_monitor_reports_a_delayed_tick_with_recent_context(qapp, caplog, monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level(logging.INFO, logger="carvex.performance")
    parent = QWidget()
    monitor = UiEventLoopMonitor(parent, interval_ms=10, threshold_ms=1)
    try:
        with performance.operation("Correlation", "filter"):
            sleep(0.02)
        monitor._on_tick()

        assert "[UI] EVENT LOOP STARVATION" in caplog.text
        assert "Correlation.filter" in caplog.text
    finally:
        monitor.close()
