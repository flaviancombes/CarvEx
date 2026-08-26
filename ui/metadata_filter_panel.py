"""Contrôles Qt légers pour interroger exclusivement ``MetadataIndex``."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLineEdit, QToolButton

from metadata.index import MetadataIndex
from metadata.query import MetadataPredicate, MetadataQuery


class MetadataFilterPanel(QGroupBox):
    """Construit des requêtes immuables sans appeler de provider ni de cache."""

    query_changed = Signal(object)
    sort_changed = Signal(str)

    _CATEGORY_LABELS = {
        "": "Toutes les catégories",
        "general": "Général",
        "filesystem": "Système de fichiers",
        "exif": "EXIF",
        "iptc": "IPTC",
        "xmp": "XMP",
        "video": "Vidéo",
        "audio": "Audio",
        "office": "Office",
        "pdf": "PDF",
        "archives": "Archives",
        "executable": "Exécutable",
        "forensic": "Forensic",
    }

    def __init__(self, parent=None) -> None:
        super().__init__("Filtres métadonnées", parent)
        self._index: MetadataIndex | None = None
        self._predicates: list[MetadataPredicate] = []
        layout = QHBoxLayout(self)
        self.category = QComboBox(self)
        self.field = QComboBox(self)
        self.mode = QComboBox(self)
        self.mode.addItem("Présent", (True, False))
        self.mode.addItem("Absent", (False, False))
        self.mode.addItem("Égal à", (True, True))
        self.value = QLineEdit(self)
        self.value.setPlaceholderText("Valeur")
        self.text = QLineEdit(self)
        self.text.setPlaceholderText("Rechercher dans les métadonnées…")
        self.add_button = QToolButton(self)
        self.add_button.setText("Ajouter")
        self.clear_button = QToolButton(self)
        self.clear_button.setText("Effacer")
        self.sort_field = QComboBox(self)
        self.sort_field.addItem("Tri : aucune métadonnée", "")
        for widget in (
            self.category,
            self.field,
            self.mode,
            self.value,
            self.add_button,
            self.clear_button,
            self.text,
            self.sort_field,
        ):
            layout.addWidget(widget)
        self.category.currentIndexChanged.connect(self._populate_fields)
        self.mode.currentIndexChanged.connect(self._update_value_visibility)
        self.add_button.clicked.connect(self._add_predicate)
        self.clear_button.clicked.connect(self.clear)
        self.text.textChanged.connect(self._emit_query)
        self.sort_field.currentIndexChanged.connect(lambda _index: self.sort_changed.emit(self.sort_identifier))
        self._set_enabled(False)

    @property
    def sort_identifier(self) -> str:
        return str(self.sort_field.currentData() or "")

    def set_index(self, index: MetadataIndex | None) -> None:
        self._index = index
        self._predicates.clear()
        self._populate_categories()
        self._populate_fields()
        self._set_enabled(index is not None and bool(index.identifiers()))
        self._emit_query()

    def refresh_index(self) -> None:
        """Refreshes dynamic choices after a committed metadata batch."""
        category = str(self.category.currentData() or "")
        field = str(self.field.currentData() or "")
        sort_identifier = self.sort_identifier
        self._populate_categories(category)
        self._populate_fields()
        self._restore_current_data(self.field, field)
        self._restore_current_data(self.sort_field, sort_identifier)
        self._set_enabled(self._index is not None and bool(self._index.identifiers()))

    def _populate_categories(self, selected: str = "") -> None:
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(self._CATEGORY_LABELS[""], "")
        if self._index is not None:
            for category, label in self._CATEGORY_LABELS.items():
                if category and self._index.by_category(category):
                    self.category.addItem(label, category)
        self._restore_current_data(self.category, selected)
        self.category.blockSignals(False)

    def clear(self) -> None:
        self._predicates.clear()
        self.text.clear()
        self._emit_query()

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.category,
            self.field,
            self.mode,
            self.value,
            self.add_button,
            self.clear_button,
            self.text,
            self.sort_field,
        ):
            widget.setEnabled(enabled)

    def _populate_fields(self, *_args) -> None:
        index = self._index
        category = str(self.category.currentData() or "")
        identifiers = (
            () if index is None else (index.identifiers_by_category(category) if category else index.identifiers())
        )
        self.field.clear()
        self.sort_field.blockSignals(True)
        self.sort_field.clear()
        self.sort_field.addItem("Tri : aucune métadonnée", "")
        for identifier in identifiers:
            self.field.addItem(identifier, identifier)
            self.sort_field.addItem(f"Tri : {identifier}", identifier)
        self.sort_field.blockSignals(False)

    @staticmethod
    def _restore_current_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _update_value_visibility(self, *_args) -> None:
        raw = self.mode.currentData()
        expects_value = bool(raw[1]) if isinstance(raw, tuple) else False
        self.value.setVisible(expects_value)

    def _add_predicate(self) -> None:
        identifier = str(self.field.currentData() or "")
        raw = self.mode.currentData()
        if not identifier or not isinstance(raw, tuple):
            return
        present, expects_value = raw
        value = self.value.text().strip() if expects_value else None
        if expects_value and not value:
            return
        predicate = MetadataPredicate(identifier, value, present)
        if predicate not in self._predicates:
            self._predicates.append(predicate)
        self._emit_query()

    def _emit_query(self, *_args) -> None:
        self.query_changed.emit(MetadataQuery(tuple(self._predicates), self.text.text()))
