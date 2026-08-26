"""Événements de progression communs au pipeline PhotoRec et à ses consommateurs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ImportProgress:
    """Avancement immutable d'une phase d'import, indépendant de Qt et de la console."""

    phase: str
    message: str
    completed: int | None = None
    total: int | None = None

    @property
    def percent(self) -> int | None:
        if self.completed is None or not self.total:
            return None
        return min(100, round(self.completed * 100 / self.total))

    @property
    def detail(self) -> str:
        if self.completed is None or self.total is None:
            return self.message
        return f"{self.message}\n{self.completed} / {self.total} fichiers"


class ImportProgressReporter:
    """Diffuse les mises à jour utiles sans saturer les consommateurs UI ou console."""

    def __init__(self, callback: Callable[[ImportProgress], None] | None) -> None:
        self._callback = callback
        self._last_percent: dict[str, int | None] = {}

    def report(self, phase: str, message: str, completed: int | None = None, total: int | None = None) -> None:
        update = ImportProgress(phase, message, completed, total)
        if self._callback is None or not self._should_emit(update):
            return
        self._callback(update)

    def _should_emit(self, update: ImportProgress) -> bool:
        percent = update.percent
        previous = self._last_percent.get(update.phase)
        if percent is None:
            if previous is None and update.phase in self._last_percent:
                return False
            self._last_percent[update.phase] = None
            return True
        if percent in {0, 100} or percent != previous:
            self._last_percent[update.phase] = percent
            return True
        return False
