"""Explorateur de fichiers : recherche, filtres et tableau Qt."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from PySide6.QtCore import QEvent, QModelIndex, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bookmarks.service import BookmarkService
from core.duplicates import DuplicateIndex
from metadata.correlation import MetadataCorrelationType
from metadata.index import MetadataIndex
from metadata.query import MetadataQuery
from models.file_table_model import FileTableModel
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.file_selection import FileSelectionChange, FileSelectionModel
from ui.bookmark_delegate import BookmarkStarDelegate
from ui.correlation_panel import CorrelationFilterPanel
from ui.file_actions import FileActions
from ui.file_filter_proxy import FileFilterProxyModel
from ui.investigation_context_menu import append_investigation_actions
from ui.metadata_filter_panel import MetadataFilterPanel


class _FileSelectionDelegate(QStyledItemDelegate):
    """Relaye explicitement le clic de case vers le rÃ´le Qt du modÃ¨le."""

    def editorEvent(self, event, model, option, index):  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonRelease and option.rect.contains(event.position().toPoint()):
            current = index.data(Qt.ItemDataRole.CheckStateRole)
            state = Qt.CheckState.Unchecked if current == Qt.CheckState.Checked else Qt.CheckState.Checked
            return model.setData(index, state, Qt.ItemDataRole.CheckStateRole)
        return super().editorEvent(event, model, option, index)


class FileTable(QWidget):
    """Widget MVC pour parcourir efficacement les fichiers d'un rapport."""

    record_selected = Signal(object)
    investigation_item_requested = Signal(object)
    status_message = Signal(str)
    view_state_changed = Signal(str, int)
    bulk_investigation_requested = Signal(object)
    bulk_collection_requested = Signal(object)
    bulk_export_requested = Signal(object)
    correlation_summary_changed = Signal(object)

    CATEGORY_FILTERS = (
        ("Tous", "", "Tous"),
        ("📄 Documents", "Documents", "Documents"),
        ("🖼 Images", "Images", "Images"),
        ("📜 Code", "Code", "Code"),
        ("🗜 Archives", "Archives", "Archives"),
        ("💾 Bases de données", "Databases", "Bases de données"),
        ("❓ Unknown", "Unknown", "Unknown"),
    )

    ARTIFACT_FILTERS = (
        ("Artefacts : tous", ""),
        ("Images avec GPS", "image.gps"),
        ("Images avec EXIF", "image.exif"),
        ("Images sans EXIF", "image.no_exif"),
        ("Photos de smartphone", "image.smartphone"),
        ("Photos d'appareil photo", "image.camera"),
        ("Images modifiées", "image.modified"),
    )

    def __init__(
        self,
        parent=None,
        artifact_cache=None,
        artifact_preloader=None,
        bookmark_service: BookmarkService | None = None,
        entity_resolver: CanonicalEntityResolver | None = None,
        file_selection: FileSelectionModel | None = None,
        duplicate_index: DuplicateIndex | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fileTable")
        self._entity_resolver = entity_resolver or CanonicalEntityResolver()
        self.duplicate_index = duplicate_index or DuplicateIndex()
        self.file_selection = file_selection or FileSelectionModel(self)
        self._source_model = FileTableModel(
            bookmark_service=bookmark_service,
            entity_resolver=self._entity_resolver,
            file_selection=self.file_selection,
            duplicate_index=self.duplicate_index,
            parent=self,
        )
        self._proxy_model = FileFilterProxyModel(
            artifact_cache=artifact_cache,
            duplicate_index=self.duplicate_index,
            parent=self,
        )
        self._artifact_preloader = artifact_preloader
        self._proxy_model.setSourceModel(self._source_model)
        self._shortcuts: list[QShortcut] = []
        self._record_rows: dict[int, int] | None = None
        self._records: Sequence[Mapping[str, Any]] = ()
        self._view_state_update_pending = False
        self._last_selected_file_id: str | None = None
        self._selection_restore_pending = False
        self._investigation_item_lookup: Callable[[Mapping[str, Any]], bool] | None = None
        self._metadata_index: MetadataIndex | None = None
        self.file_actions = FileActions(self)
        self.file_actions.status_message.connect(self.status_message)

        self.search_field = QLineEdit(self)
        self.search_field.setPlaceholderText("Rechercher un nom, hash, type ou chemin…")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._set_search_text)

        filters = self._create_filters()
        self.metadata_filters = MetadataFilterPanel(self)
        self.metadata_filters.query_changed.connect(self.set_metadata_query)
        self.metadata_filters.sort_changed.connect(self._proxy_model.set_metadata_sort_identifier)
        self.correlation_filters = CorrelationFilterPanel(self)
        self.correlation_filters.matches_changed.connect(self._apply_correlation_matches)
        self.view = QTableView(self)
        self.view.setModel(self._proxy_model)
        self.view.setItemDelegateForColumn(FileTableModel.SELECTION_COLUMN, _FileSelectionDelegate(self.view))
        self.view.setItemDelegateForColumn(FileTableModel.BOOKMARK_COLUMN, BookmarkStarDelegate(self.view))
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setWordWrap(False)
        self.view.setSortingEnabled(False)
        self.view.verticalHeader().setVisible(False)
        self.view.selectionModel().currentRowChanged.connect(self._emit_selected_record)
        self.view.clicked.connect(lambda index: self._emit_selected_record(index, QModelIndex()))
        self.view.doubleClicked.connect(self._open_file_at_index)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        self._create_shortcuts()

        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        header.sectionClicked.connect(self._handle_header_click)
        self.view.setColumnWidth(FileTableModel.SELECTION_COLUMN, 32)
        self.view.setColumnWidth(FileTableModel.BOOKMARK_COLUMN, 38)
        self.view.setColumnWidth(FileTableModel.INVESTIGATION_COLUMN, 30)
        self.view.setColumnWidth(3, 260)
        self.view.setColumnWidth(4, 140)
        self.view.setColumnWidth(5, 190)
        self.view.setColumnWidth(6, 100)
        self.view.setColumnWidth(FileTableModel.DUPLICATE_COUNT_COLUMN, 120)
        self.view.setColumnWidth(FileTableModel.CORRELATIONS_COLUMN, 110)

        self.bulk_bar = self._create_bulk_bar()
        self.file_selection.changed.connect(self._on_bulk_selection_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.search_field)
        layout.addWidget(filters)
        layout.addWidget(self.metadata_filters)
        layout.addWidget(self.correlation_filters)
        layout.addWidget(self.bulk_bar)
        layout.addWidget(self.view, 1)

    def _create_bulk_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(bar)
        self.bulk_label = QToolButton(bar)
        self.bulk_label.setEnabled(False)
        layout.addWidget(self.bulk_label)
        for text, callback in (
            (
                "Ajouter à Investigation",
                lambda: self.bulk_investigation_requested.emit(self.file_selection.selected_ids()),
            ),
            ("Ajouter à Collection", lambda: self.bulk_collection_requested.emit(self.file_selection.selected_ids())),
            ("Bookmark", self._bookmark_selected),
            ("Exporter", lambda: self.bulk_export_requested.emit(self.file_selection.selected_ids())),
            ("Copier chemins", lambda: self._copy_selected("output")),
            ("Copier SHA", lambda: self._copy_selected("sha256")),
            ("Désélectionner", self.file_selection.clear),
        ):
            button = QToolButton(bar)
            button.setText(text)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch()
        bar.hide()
        return bar

    def _create_filters(self) -> QWidget:
        container = QWidget(self)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        for label, category, category_label in self.CATEGORY_FILTERS:
            button = QToolButton(container)
            button.setText(label)
            button.setCheckable(True)
            button.setProperty("category", category)
            button.setProperty("category_label", category_label)
            self.category_group.addButton(button)
            layout.addWidget(button)
            if not category:
                button.setChecked(True)
        layout.addStretch()
        self.duplicates_filter = QToolButton(container)
        self.duplicates_filter.setText("Afficher uniquement les doublons")
        self.duplicates_filter.setCheckable(True)
        self.duplicates_filter.toggled.connect(self._apply_duplicates_filter)
        layout.addWidget(self.duplicates_filter)
        self.category_group.idClicked.connect(self._apply_category_filter)
        self.artifact_filter = QComboBox(container)
        for label, filter_id in self.ARTIFACT_FILTERS:
            self.artifact_filter.addItem(label, filter_id)
        self.artifact_filter.currentIndexChanged.connect(self._apply_artifact_filter)
        layout.addWidget(self.artifact_filter)
        return container

    def _apply_category_filter(self, button_id: int) -> None:
        self._remember_current_file()
        button = self.category_group.button(button_id)
        self._proxy_model.set_category(str(button.property("category")))
        self._emit_view_state()
        self._restore_last_selection()

    def _apply_artifact_filter(self, _index: int) -> None:
        self._remember_current_file()
        artifact_filter = str(self.artifact_filter.currentData() or "")
        self._proxy_model.set_artifact_filter(artifact_filter)
        if artifact_filter and self._artifact_preloader is not None:
            self._artifact_preloader.preload(self._records)
        self._emit_view_state()
        self._restore_last_selection()

    def _apply_duplicates_filter(self, enabled: bool) -> None:
        self._remember_current_file()
        self._proxy_model.set_duplicates_only(enabled)
        self._emit_view_state()
        self._restore_last_selection()

    def refresh_artifact_filter(self, file_ids: Sequence[str]) -> None:
        """Réévalue uniquement les lignes dont le cache d'artefacts vient d'être rempli."""
        if self._proxy_model.artifact_filter and file_ids:
            self._proxy_model.refresh_artifact_rows(file_ids)
            self._source_model.refresh_artifact_rows(file_ids)
            self._emit_view_state()

    def set_investigation_file_lookup(self, lookup: Callable[[str], bool] | None) -> None:
        """Configure un prédicat O(1) fourni par l'orchestrateur, jamais un repository."""
        self._source_model.set_investigation_file_lookup(lookup)

    def refresh_investigation_marker(self, file_id: str | None = None) -> None:
        self._source_model.refresh_investigation_marker(file_id)

    def refresh_investigation_markers(self, file_ids: Iterable[str]) -> None:
        """Notifie un lot borné de cellules d'indicateur, sans reset de modèle."""
        self._source_model.refresh_investigation_markers(tuple(file_ids))

    def set_investigation_item_lookup(self, lookup: Callable[[Mapping[str, Any]], bool] | None) -> None:
        self._investigation_item_lookup = lookup

    def _set_search_text(self, text: str) -> None:
        self._remember_current_file()
        metadata_matches = self._metadata_index.search(text) if self._metadata_index else frozenset()
        correlation_matches = self.correlation_filters.search_matches(text)
        self._proxy_model.set_universal_search(text, metadata_matches | correlation_matches)
        self._emit_view_state()
        self._restore_last_selection()

    def set_metadata_index(self, index: MetadataIndex | None) -> None:
        """Makes the persistent metadata index available to the filters only."""
        self._metadata_index = index
        self._source_model.set_metadata_index(index)
        self._proxy_model.set_metadata_index(index)
        self.metadata_filters.set_index(index)

    def set_correlation_index(self, index) -> None:
        """Raccorde uniquement la projection d'un index déjà persistant."""
        self._source_model.set_correlation_index(index)
        self.correlation_filters.set_index(index)
        if index is None:
            self.correlation_summary_changed.emit({"files": 0, "anomalies": 0, "gps": 0, "devices": 0})
            return
        correlations = index.all()
        affected = {file_id for correlation in correlations for file_id in correlation.file_ids}
        anomaly_types = {
            MetadataCorrelationType.DATES_INCONSISTENT,
            MetadataCorrelationType.TIMEZONES_INCONSISTENT,
            MetadataCorrelationType.ORIENTATION_INCONSISTENT,
            MetadataCorrelationType.RESOLUTION_INCONSISTENT,
            MetadataCorrelationType.XMP_WITHOUT_SOFTWARE,
            MetadataCorrelationType.GPS_WITHOUT_TIMESTAMP,
            MetadataCorrelationType.THUMBNAIL_WITHOUT_EXIF,
            MetadataCorrelationType.ICC_WITHOUT_COLORSPACE,
        }
        self.correlation_summary_changed.emit(
            {
                "files": len(affected),
                "anomalies": sum(item.correlation_type in anomaly_types for item in correlations),
                "gps": sum(item.correlation_type.value in {"same_gps", "nearby_gps"} for item in correlations),
                "devices": sum(item.correlation_type.value == "same_device" for item in correlations),
            }
        )

    def _apply_correlation_matches(self, matches: frozenset[str] | None) -> None:
        self._remember_current_file()
        self._proxy_model.set_correlation_matches(matches)
        self._emit_view_state()
        self._restore_last_selection()

    def show_correlated_files(self, record: Mapping[str, Any]) -> None:
        file_id = self._entity_resolver.file_id_for(record)
        if file_id is not None:
            self.correlation_filters.show_related_to(file_id)

    def file_label_for(self, file_id: str) -> str:
        return self._source_model.file_label_for(file_id)

    def set_metadata_query(self, query: MetadataQuery) -> None:
        self._proxy_model.set_metadata_query(query)
        self._emit_view_state()

    def refresh_metadata_filters(self) -> None:
        """Re-evaluates the active immutable query after an index batch commit."""
        self.metadata_filters.refresh_index()
        self._proxy_model.refresh_metadata_query()
        self._emit_view_state()

    def _emit_view_state(self) -> None:
        """Diffère le comptage afin de ne pas forcer le proxy juste après son invalidation."""
        if self._view_state_update_pending:
            return
        self._view_state_update_pending = True
        QTimer.singleShot(0, self._emit_deferred_view_state)

    def _emit_deferred_view_state(self) -> None:
        self._view_state_update_pending = False
        button = self.category_group.checkedButton()
        category = str(button.property("category_label")) if button else "Tous"
        if self.artifact_filter.currentData():
            category = str(self.artifact_filter.currentText())
        self.view_state_changed.emit(category, self._proxy_model.rowCount())

    def _emit_selected_record(self, current: QModelIndex, _previous: QModelIndex) -> None:
        record = self.record_for_index(current)
        if record is not None:
            self._last_selected_file_id = self._entity_resolver.file_id_for(record)
        self.record_selected.emit(record)

    def _handle_header_click(self, section: int) -> None:
        if section == FileTableModel.SELECTION_COLUMN:
            self._toggle_header_selection()
            if self._proxy_model.sortColumn() == FileTableModel.SELECTION_COLUMN:
                self.restore_sort_state(FileTableModel.SELECTION_COLUMN, Qt.SortOrder.AscendingOrder)
            return
        header = self.view.horizontalHeader()
        order = (
            Qt.SortOrder.DescendingOrder
            if header.sortIndicatorSection() == section and header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
        self.restore_sort_state(section, order)

    def _toggle_header_selection(self, section: int | None = None) -> None:
        if section is not None and section != FileTableModel.SELECTION_COLUMN:
            return
        visible_ids = self._visible_file_ids()
        if visible_ids and all(self.file_selection.contains(file_id) for file_id in visible_ids):
            self.file_selection.deselect_many(visible_ids)
        else:
            self.file_selection.select_many(visible_ids)

    def restore_sort_state(self, column: int, order: Qt.SortOrder) -> None:
        """Restore a business sort; the checkbox column deliberately has no sort key."""
        header = self.view.horizontalHeader()
        if column == FileTableModel.SELECTION_COLUMN:
            self._proxy_model.sort(-1, order)
            header.setSortIndicator(-1, order)
            return
        self._proxy_model.sort(column, order)
        header.setSortIndicator(column, order)

    def _visible_file_ids(self) -> tuple[str, ...]:
        file_ids: list[str] = []
        for row in range(self._proxy_model.rowCount()):
            source = self._proxy_model.mapToSource(self._proxy_model.index(row, 0))
            file_id = self._source_model.file_id_at(source.row()) if source.isValid() else None
            if file_id is not None:
                file_ids.append(file_id)
        return tuple(file_ids)

    def select_all_visible(self) -> None:
        self.file_selection.select_many(self._visible_file_ids())

    def _on_bulk_selection_changed(self, _change: FileSelectionChange) -> None:
        count = self.file_selection.count
        self.bulk_label.setText(f"{count} fichier(s) sélectionné(s)")
        self.bulk_bar.setVisible(bool(count))

    def _selected_records(self) -> tuple[Mapping[str, Any], ...]:
        selected = self.file_selection.selected_ids()
        return tuple(record for record in self._records if self._entity_resolver.file_id_for(record) in selected)

    def _bookmark_selected(self) -> None:
        service = self._source_model.bookmark_service
        if service is None:
            return
        from bookmarks.model import BookmarkKey

        result = service.add_many(BookmarkKey("file", file_id) for file_id in self.file_selection.selected_ids())
        self.status_message.emit(f"{len(result.added_keys)} bookmark(s) ajouté(s).")

    def _copy_selected(self, field: str) -> None:
        values = [str(record.get(field) or "") for record in self._selected_records()]
        values = [value for value in values if value]
        QApplication.clipboard().setText("\n".join(values))
        self.status_message.emit(f"{len(values)} valeur(s) copiée(s).")

    def _create_shortcuts(self) -> None:
        self._shortcut(QKeySequence("Return"), self._open_current_file)
        self._shortcut(QKeySequence("Enter"), self._open_current_file)
        self._shortcut(QKeySequence("Ctrl+O"), self._open_current_file)
        self._shortcut(QKeySequence("Ctrl+Shift+O"), self._open_current_folder)
        self._shortcut(QKeySequence("Ctrl+C"), self._copy_selection)
        self._shortcut(QKeySequence("Ctrl+Shift+C"), lambda: self._copy_current("output", "Chemin exporté"))

    def _shortcut(self, sequence: QKeySequence, callback) -> None:
        shortcut = QShortcut(sequence, self.view)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)

    def _show_context_menu(self, position: QPoint) -> None:
        index = self.view.indexAt(position)
        if not index.isValid():
            return
        self.view.setCurrentIndex(index)
        record = self.record_for_index(index)
        if record is not None:
            self._context_menu_for_record(record).exec(self.view.viewport().mapToGlobal(position))

    def _context_menu_for_record(self, record: Mapping[str, Any]):
        """Ajoute des intentions Investigation sans étendre les actions Windows existantes."""
        menu = self.file_actions.create_context_menu(record, self.view)
        append_investigation_actions(
            menu,
            is_present=bool(self._investigation_item_lookup and self._investigation_item_lookup(record)),
            edit_evidence=lambda: self.investigation_item_requested.emit(record),
        )
        file_id = self._entity_resolver.file_id_for(record)
        if file_id is not None and self._source_model.correlation_count_for_file(file_id):
            menu.addAction("Voir tous les fichiers corrélés", lambda: self.show_correlated_files(record))
        return menu

    def _open_file_at_index(self, index: QModelIndex) -> None:
        record = self.record_for_index(index)
        if record is not None:
            self.file_actions.open_file(record, self.window())

    def _open_current_file(self) -> None:
        self._open_file_at_index(self.view.currentIndex())

    def find_next_result(self, backwards: bool = False) -> None:
        count = self._proxy_model.rowCount()
        if not count:
            return
        current = self.view.currentIndex().row()
        row = (current - 1 if backwards else current + 1) % count
        self.view.setCurrentIndex(self._proxy_model.index(row, 0))
        self.view.scrollTo(self._proxy_model.index(row, 0))

    def focus_filters(self) -> None:
        button = self.category_group.checkedButton() or next(iter(self.category_group.buttons()), None)
        if button is not None:
            button.setFocus()

    def workspace_state(self) -> dict[str, str]:
        return self.correlation_filters.state()

    def restore_workspace_state(self, state: dict[str, str]) -> None:
        self.correlation_filters.restore_state(state)

    def _remember_current_file(self) -> None:
        record = self.record_for_index(self.view.currentIndex())
        if record is not None:
            self._last_selected_file_id = self._entity_resolver.file_id_for(record)

    def _restore_last_selection(self) -> None:
        if self._selection_restore_pending:
            return
        self._selection_restore_pending = True
        QTimer.singleShot(0, self._restore_last_selection_deferred)

    def _restore_last_selection_deferred(self) -> None:
        self._selection_restore_pending = False
        if self._last_selected_file_id is None:
            return
        row = self._source_model.row_for_file(self._last_selected_file_id)
        if row is not None:
            self._select_source_row(row)

    def _open_current_folder(self) -> None:
        record = self.record_for_index(self.view.currentIndex())
        if record is not None:
            self.file_actions.open_containing_folder(record, self.window())

    def _copy_current(self, field: str, label: str) -> None:
        record = self.record_for_index(self.view.currentIndex())
        if record is not None:
            self.file_actions.copy_value(record, field, label)

    def _copy_selection(self) -> None:
        index = self.view.currentIndex()
        if index.isValid():
            if index.column() in {
                FileTableModel.SELECTION_COLUMN,
                FileTableModel.BOOKMARK_COLUMN,
                FileTableModel.INVESTIGATION_COLUMN,
            }:
                record = self.record_for_index(index)
                value = record.get("name") if record is not None else ""
            else:
                value = index.data(Qt.ItemDataRole.DisplayRole)
            QApplication.clipboard().setText(str(value or ""))

    @property
    def file_count(self) -> int:
        return self._source_model.rowCount()

    @property
    def visible_file_count(self) -> int:
        """Retourne le nombre de lignes actuellement exposées par le proxy Qt."""
        return self._proxy_model.rowCount()

    def set_files(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Affiche les enregistrements backend sans les dupliquer."""
        self._records = records
        self._record_rows = None
        self.duplicate_index.build(records)
        self._proxy_model.clear_artifact_matches()
        self._source_model.set_records(records)
        self._proxy_model.refresh_metadata_query()
        if self._proxy_model.artifact_filter and self._artifact_preloader is not None:
            self._artifact_preloader.preload(records)
        self._emit_view_state()

    def record_for_index(self, index: QModelIndex) -> Mapping[str, Any] | None:
        """Récupère l'enregistrement source complet à partir d'un index proxy."""
        if not index.isValid():
            return None
        source_index = self._proxy_model.mapToSource(index)
        return self._source_model.record_at(source_index.row())

    def select_record(self, file_record: Mapping[str, Any]) -> bool:
        """Sélectionne un enregistrement existant sans recréer le modèle ni les données."""
        target_key = self._entity_resolver.file_id_for(file_record)
        if target_key is None:
            return False
        if self._record_rows is None:
            self._record_rows = {id(record): row for row, record in enumerate(self._records)}
        row = self._record_rows.get(id(file_record))
        if row is not None and self._select_source_row(row):
            return True
        for row in range(self._source_model.rowCount()):
            record = self._source_model.record_at(row)
            if record is file_record or (
                record is not None and self._entity_resolver.file_id_for(record) == target_key
            ):
                return self._select_source_row(row)
        return False

    def _select_source_row(self, row: int) -> bool:
        index = self._proxy_model.mapFromSource(self._source_model.index(row, 0))
        if not index.isValid():
            return False
        self.view.setCurrentIndex(index)
        self.view.scrollTo(index)
        return True
