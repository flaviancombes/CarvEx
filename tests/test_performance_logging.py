"""Tests de persistance des journaux d'instrumentation opt-in."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from utils import performance


@pytest.fixture
def enabled_performance_logging(monkeypatch, tmp_path: Path):
    """Isole les handlers dédiés afin que chaque test contrôle son fichier."""
    performance.shutdown_performance_logging()
    monkeypatch.setattr(performance, "ENABLED", True)
    monkeypatch.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        performance.shutdown_performance_logging()


def test_performance_logging_is_inactive_without_perf(monkeypatch, tmp_path: Path):
    performance.shutdown_performance_logging()
    monkeypatch.setattr(performance, "ENABLED", False)
    monkeypatch.chdir(tmp_path)

    assert performance.configure_performance_logging() is None
    performance.LOGGER.info("message absent")

    assert not (tmp_path / performance.PERFORMANCE_LOG_FILENAME).exists()


def test_performance_logging_writes_utf8_info_and_ui_block(enabled_performance_logging: Path):
    log_path = performance.configure_performance_logging()
    assert log_path == enabled_performance_logging / performance.PERFORMANCE_LOG_FILENAME

    performance.LOGGER.info("métadonnées prêtes")
    performance.LOGGER.warning("[UI] BLOCK >100ms opération test")
    performance.flush_performance_logging()

    contents = log_path.read_text(encoding="utf-8")
    assert "métadonnées prêtes" in contents
    assert "[UI] BLOCK >100ms opération test" in contents


def test_performance_logging_configuration_is_idempotent(enabled_performance_logging: Path):
    first_path = performance.configure_performance_logging()
    second_path = performance.configure_performance_logging()

    assert first_path == second_path == enabled_performance_logging / performance.PERFORMANCE_LOG_FILENAME
    handlers = performance._performance_handlers()
    assert len(handlers) == 2
    assert len(performance._performance_handlers("file")) == 1
    assert len(performance._performance_handlers("stream")) == 1
    assert all(handler.level == logging.NOTSET for handler in handlers)


def test_timing_mode_does_not_enable_costly_allocation_tracking_by_default(caplog, monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    monkeypatch.setattr(performance, "ALLOCATION_TRACKING_ENABLED", False)
    monkeypatch.setattr(performance.tracemalloc, "is_tracing", lambda: False)
    monkeypatch.setattr(
        performance.tracemalloc,
        "start",
        lambda: (_ for _ in ()).throw(AssertionError("tracemalloc ne doit pas être démarré")),
    )
    caplog.set_level(logging.INFO, logger="carvex.performance")

    with performance.measure("timing-only"):
        pass

    assert "allocated_kib=disabled" in caplog.text
    assert "peak_kib=disabled" in caplog.text
