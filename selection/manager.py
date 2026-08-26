"""Point central de diffusion de la sélection, sans logique métier ni graphique."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from selection.context import SelectionContext


class SelectionManager(QObject):
    """Publie une sélection légère et conserve un historique borné en mémoire."""

    selection_changed = Signal(object)

    def __init__(self, history_limit: int = 100, parent=None) -> None:
        super().__init__(parent)
        self._history_limit = max(1, history_limit)
        self._history: list[SelectionContext] = []
        self._cursor = -1
        self._current: SelectionContext | None = None
        self._next_selection_id = 1

    @property
    def current(self) -> SelectionContext | None:
        return self._current

    @property
    def can_go_back(self) -> bool:
        return self._cursor > 0

    @property
    def can_go_forward(self) -> bool:
        return 0 <= self._cursor < len(self._history) - 1

    def publish(self, context: SelectionContext) -> None:
        """Diffuse une nouvelle cible et coupe la branche avant de l'historique."""
        if context.has_same_target(self._current):
            # Un clic utilisateur sur la sélection courante doit tout de même
            # resynchroniser les consommateurs (DetailsPanel, vues liées), sans
            # polluer l'historique de navigation.
            stamped = replace(context, selection_id=self._next_selection_id)
            self._next_selection_id += 1
            self._set_current(stamped)
            return
        stamped = replace(context, selection_id=self._next_selection_id)
        self._next_selection_id += 1
        del self._history[self._cursor + 1 :]
        self._history.append(stamped)
        if len(self._history) > self._history_limit:
            self._history.pop(0)
        self._cursor = len(self._history) - 1
        self._set_current(stamped)

    def clear_current(self) -> None:
        """Efface l'affichage courant sans détruire l'historique de navigation."""
        if self._current is None:
            return
        self._current = None
        self.selection_changed.emit(None)

    def go_back(self) -> SelectionContext | None:
        if not self.can_go_back:
            return None
        self._cursor -= 1
        self._set_current(self._history[self._cursor])
        return self._current

    def go_forward(self) -> SelectionContext | None:
        if not self.can_go_forward:
            return None
        self._cursor += 1
        self._set_current(self._history[self._cursor])
        return self._current

    def clear_history(self) -> None:
        self._history.clear()
        self._cursor = -1
        self.clear_current()

    def _set_current(self, context: SelectionContext) -> None:
        self._current = context
        self.selection_changed.emit(context)
