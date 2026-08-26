"""Menu contextuel Investigation réutilisable par les vues Qt de CarvEx."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QMenu


def append_investigation_actions(
    menu: QMenu,
    *,
    is_present: bool,
    edit_evidence: Callable[[], None],
) -> None:
    """Ajoute les mêmes intentions Investigation sans connaître le domaine ni les vues sources."""
    menu.addSeparator()
    if is_present:
        menu.addAction("\u2713 D\u00e9j\u00e0 pr\u00e9sent", edit_evidence)
        return
    menu.addAction("Ajouter \u00e0 Investigation", edit_evidence)
