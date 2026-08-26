"""Instrumentation passive de la phase terminale de l'indexation."""

from __future__ import annotations

import logging
from time import sleep

from utils import performance


def test_indexing_completion_report_logs_each_stage_and_total(caplog, monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level(logging.INFO, logger="carvex.performance")
    report = performance.IndexingCompletionReport()

    with report.stage("Corrélations"):
        pass
    report.record_elapsed("Flush projet", 1.5)
    report.finish()

    assert [entry.label for entry in report.entries] == ["Corrélations", "Flush projet", "Interface prête"]
    assert "[Indexation] Corrélations" in caplog.text
    assert "[Indexation] Temps total post-indexation" in caplog.text


def test_pipeline_profile_aggregates_repeated_nested_stages(caplog, monkeypatch):
    monkeypatch.setattr(performance, "ENABLED", True)
    caplog.set_level(logging.INFO, logger="carvex.performance")
    performance.start_pipeline_profile("Pipeline test")
    with performance.pipeline_stage("Commit"):
        with performance.pipeline_stage("Index"):
            sleep(0.055)
    with performance.pipeline_stage("Commit"):
        with performance.pipeline_stage("Index"):
            sleep(0.055)
    performance.finish_pipeline_profile()

    assert "[Profil] Pipeline test" in caplog.text
    assert "Commit — appels: 2" in caplog.text
    assert "Index — appels: 2" in caplog.text
