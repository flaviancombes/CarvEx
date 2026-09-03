"""Registre léger des tâches applicatives significatives en arrière-plan."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from utils import performance


@dataclass(frozen=True, slots=True)
class BackgroundTask:
    """État immuable d'une tâche visible à l'utilisateur."""

    task_id: str
    label: str
    current: int | None = None
    total: int | None = None
    started_at: float = 0.0

    @property
    def is_determinate(self) -> bool:
        return self.current is not None and self.total is not None and self.total > 0

    @property
    def percentage(self) -> int | None:
        if not self.is_determinate:
            return None
        assert self.current is not None and self.total is not None
        return min(100, max(0, int(self.current * 100 / self.total)))


class BackgroundTaskRegistry(QObject):
    """Source unique des tâches applicatives actives, sans polling ni persistance."""

    tasks_changed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks: dict[str, BackgroundTask] = {}
        self._last_logged_percentage: dict[str, int | None] = {}

    @property
    def active_tasks(self) -> tuple[BackgroundTask, ...]:
        return tuple(self._tasks.values())

    @property
    def is_ready(self) -> bool:
        return not self._tasks

    def task(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def start_task(self, task_id: str, label: str, total: int | None = None, current: int | None = 0) -> None:
        if not task_id or not label:
            raise ValueError("Une tâche d'arrière-plan exige un identifiant et un libellé.")
        if total is not None and total < 0:
            raise ValueError("Le total d'une tâche ne peut pas être négatif.")
        task = BackgroundTask(task_id, label, current if total is not None else None, total, perf_counter())
        self._tasks[task_id] = task
        self._last_logged_percentage.pop(task_id, None)
        self._log("START id=%s label=%s current=%s total=%s", task_id, label, task.current, total)
        self._emit_changed()

    def update_task(
        self,
        task_id: str,
        *,
        current: int | None = None,
        total: int | None = None,
        label: str | None = None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        updated_total = task.total if total is None else total
        updated_current = task.current if current is None else current
        updated = replace(
            task, label=task.label if label is None else label, current=updated_current, total=updated_total
        )
        if updated == task:
            return
        self._tasks[task_id] = updated
        self._log_progress(updated)
        self._emit_changed()

    def set_phase(self, task_id: str, label: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        updated = replace(task, label=label, current=None, total=None)
        if updated == task:
            return
        self._tasks[task_id] = updated
        self._log("PHASE id=%s label=%s", task_id, label)
        self._emit_changed()

    def finish_task(self, task_id: str, *, cancelled: bool = False) -> None:
        task = self._tasks.pop(task_id, None)
        self._last_logged_percentage.pop(task_id, None)
        if task is None:
            return
        self._log(
            "END id=%s cancelled=%s duration_ms=%.2f",
            task_id,
            cancelled,
            (perf_counter() - task.started_at) * 1_000,
        )
        self._emit_changed()

    def finish_all(self, *, cancelled: bool = True) -> None:
        for task_id in tuple(self._tasks):
            self.finish_task(task_id, cancelled=cancelled)

    def _emit_changed(self) -> None:
        self.tasks_changed.emit(self.active_tasks)
        self._log("ACTIVE count=%d", len(self._tasks))
        if not self._tasks:
            self._log("READY")

    def _log_progress(self, task: BackgroundTask) -> None:
        percentage = task.percentage
        if percentage == self._last_logged_percentage.get(task.task_id):
            return
        self._last_logged_percentage[task.task_id] = percentage
        self._log(
            "PROGRESS id=%s current=%s total=%s percentage=%s",
            task.task_id,
            task.current,
            task.total,
            percentage,
        )

    @staticmethod
    def _log(message: str, *args: object) -> None:
        if performance.ENABLED:
            performance.LOGGER.info("[BackgroundTask] " + message, *args)


class BackgroundActivityIndicator(QWidget):
    """Projection sobre du registre dans la barre d'état."""

    def __init__(self, registry: BackgroundTaskRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self.label = QLabel("Prêt", self)
        self.progress = QProgressBar(self)
        self.progress.setTextVisible(True)
        self.progress.setFixedWidth(150)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        registry.tasks_changed.connect(self._render)
        self._render(registry.active_tasks)

    def _render(self, tasks: tuple[BackgroundTask, ...]) -> None:
        if not tasks:
            self.label.setText("Prêt")
            self.progress.setVisible(False)
            return
        primary = tasks[-1]
        prefix = "CarvEx travaille en arrière-plan"
        if len(tasks) > 1:
            prefix += f" — {len(tasks)} tâches actives"
        self.label.setText(f"{prefix} — {primary.label}")
        self.progress.setVisible(True)
        if primary.is_determinate:
            assert primary.current is not None and primary.total is not None
            self.progress.setRange(0, primary.total)
            self.progress.setValue(primary.current)
            self.progress.setFormat(f"{primary.current} / {primary.total} (%p%)")
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat("")
