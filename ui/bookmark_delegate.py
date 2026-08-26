"""Delegate virtualisé pour le clic étoile dans les tables Qt."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import QStyledItemDelegate


class BookmarkStarDelegate(QStyledItemDelegate):
    """Évite la création de widgets par ligne et délègue l'état au service."""

    def editorEvent(self, event, model, option, index):  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonRelease and option.rect.contains(event.pos()):
            source_model, source_index = self._source_index(model, index)
            key = source_model.bookmark_key_for_index(source_index)
            service = source_model.bookmark_service
            if key is not None and service is not None:
                service.toggle(key)
                return True
        return super().editorEvent(event, model, option, index)

    def paint(self, painter, option, index):  # noqa: N802
        painter.save()
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, str(index.data() or "☆"))
        painter.restore()

    @staticmethod
    def _source_index(model, index):
        if isinstance(model, QSortFilterProxyModel):
            return model.sourceModel(), model.mapToSource(index)
        return model, index
