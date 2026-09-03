"""Nouvel onglet Timeline, simple consommateur du service métier partagé."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from bookmarks.model import BookmarkKey
from bookmarks.service import BookmarkService
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.file_selection import FileSelectionModel
from timeline.event import TimelineEvent
from timeline.manager import TimelineManager
from timeline.model import TimelineFilterProxyModel, TimelineTableModel
from timeline.repository import TimelineBuildSession
from timeline.service import TimelineService
from ui.background_activity import BackgroundTaskRegistry
from ui.bookmark_delegate import BookmarkStarDelegate
from ui.investigation_context_menu import append_investigation_actions
from utils import performance


class _TimelineBuildWorker(QObject):
    """Execute a Timeline build session outside the Qt GUI thread."""

    batch_ready = Signal(int, object)
    progress = Signal(int, int)
    finalizing = Signal(int)
    completed = Signal(int)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        session: TimelineBuildSession,
        generation: int,
        batch_size: int = 2_048,
        projection_batch_size: int = 32_768,
    ) -> None:
        super().__init__()
        self._session = session
        self._generation = generation
        self._batch_size = batch_size
        self._projection_batch_size = projection_batch_size

    def cancel(self) -> None:
        self._session.cancel()

    @Slot()
    def run(self) -> None:
        try:
            groups: dict[str, list[TimelineEvent]] = {}
            last_progress = -1
            while True:
                events, complete = self._session.next_batch(self._batch_size)
                if events:
                    for event in events:
                        record = event.file_record or {}
                        key = str(record.get("file_id") or event.event_id)
                        groups.setdefault(key, []).append(event)
                if self._session.processed_records != last_progress:
                    last_progress = self._session.processed_records
                    self.progress.emit(self._generation, last_progress)
                if complete:
                    break
            self.finalizing.emit(self._generation)
            self._emit_chronological_batches(groups)
            self.completed.emit(self._generation)
        except Exception as error:
            self.failed.emit(self._generation, str(error))
        finally:
            self.finished.emit()

    def _emit_chronological_batches(self, groups: dict[str, list[TimelineEvent]]) -> None:
        """Emit file groups in chronological order without proxy sorting on the UI thread."""
        ordered_groups = sorted(
            enumerate(groups.values()),
            key=lambda value: (min(TimelineManager._sort_key(event) for event in value[1]), value[0]),
        )
        batch: list[TimelineEvent] = []
        for position, (_ordinal, group) in enumerate(ordered_groups, start=1):
            batch.extend(group)
            if position % self._projection_batch_size == 0:
                self.batch_ready.emit(self._generation, tuple(batch))
                batch.clear()
        if batch:
            self.batch_ready.emit(self._generation, tuple(batch))


class TimelineView(QWidget):
    event_selected = Signal(object)
    event_activated = Signal(object)
    investigation_item_requested = Signal(object)
    bulk_investigation_requested = Signal(object)
    bulk_collection_requested = Signal(object)

    CATEGORIES = ("", "Images", "Documents", "Archives", "Audio", "Video", "Databases", "Executables")

    def __init__(
        self,
        service: TimelineService,
        bookmark_service: BookmarkService | None = None,
        parent=None,
        entity_resolver: CanonicalEntityResolver | None = None,
        file_selection: FileSelectionModel | None = None,
        background_tasks: BackgroundTaskRegistry | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._bookmark_service = bookmark_service
        self._loaded = False
        self._build_session = None
        self._build_thread: QThread | None = None
        self._build_worker: _TimelineBuildWorker | None = None
        self._build_generation = 0
        self._pending_projection_batches: deque[tuple] = deque()
        self._projection_scheduled = False
        self._worker_completed = False
        self._bulk_projection_active = False
        self._projection_proxy_attached = False
        self._event_types: dict[str, object] = {}
        self._pending_event_type = ""
        self._pending_sort_state: tuple[int, Qt.SortOrder] | None = None
        self._investigation_presence_lookup: Callable[[object], bool] | None = None
        self._entity_resolver = entity_resolver or CanonicalEntityResolver()
        self._background_tasks = background_tasks
        self.file_selection = file_selection or FileSelectionModel(self)
        self._model = TimelineTableModel(
            bookmark_service=bookmark_service,
            entity_resolver=self._entity_resolver,
            file_selection=self.file_selection,
            parent=self,
        )
        self._proxy = TimelineFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Rechercher un fichier, un événement, une source ou un appareil…")
        self.search.setClearButtonEnabled(True)
        self.category = QComboBox(self)
        self.category.addItem("Toutes les catégories", "")
        for item in self.CATEGORIES[1:]:
            self.category.addItem(item, item)
        self.event_type = QComboBox(self)
        self.event_type.addItem("Tous les événements", "")
        self.table = QTreeView(self)
        self.table.setModel(self._proxy)
        self.table.setItemDelegateForColumn(TimelineTableModel.BOOKMARK_COLUMN, BookmarkStarDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setRootIsDecorated(True)
        self.table.setItemsExpandable(True)
        self.table.setExpandsOnDoubleClick(False)
        header = self.table.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionsMovable(True)
        header.setFirstSectionMovable(False)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.sectionClicked.connect(self._toggle_header_selection)
        self.table.setColumnWidth(TimelineTableModel.SELECTION_COLUMN, 32)
        self.table.setColumnWidth(TimelineTableModel.BOOKMARK_COLUMN, 38)
        self.table.setColumnWidth(TimelineTableModel.INVESTIGATION_COLUMN, 32)
        self.table.doubleClicked.connect(self._activate_index)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.selectionModel().currentRowChanged.connect(self._select_index)
        self.table.clicked.connect(lambda index: self._select_index(index, QModelIndex()))
        self.search.textChanged.connect(self._apply_filters)
        self.category.currentIndexChanged.connect(self._apply_filters)
        self.event_type.currentIndexChanged.connect(self._apply_filters)
        self._copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.table)
        self._copy_shortcut.activated.connect(self._copy_selection)
        self.bulk_bar = self._create_bulk_bar()
        self.file_selection.changed.connect(self._on_file_selection_changed)
        controls = QHBoxLayout()
        controls.addWidget(self.search, 1)
        controls.addWidget(self.category)
        controls.addWidget(self.event_type)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.bulk_bar)
        layout.addWidget(self.table, 1)

    def ensure_selection_column_first(self) -> None:
        """Preserve the selection column at the left after restoring a legacy Workspace."""
        header = self.table.header()
        selection_index = header.visualIndex(TimelineTableModel.SELECTION_COLUMN)
        if selection_index > 0:
            header.moveSection(selection_index, 0)

    def _create_bulk_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(bar)
        self.bulk_label = QToolButton(bar)
        self.bulk_label.setEnabled(False)
        layout.addWidget(self.bulk_label)
        actions = (
            (
                "Ajouter à Investigation",
                lambda: self.bulk_investigation_requested.emit(self.file_selection.selected_ids()),
            ),
            ("Ajouter à Collection", lambda: self.bulk_collection_requested.emit(self.file_selection.selected_ids())),
            ("Bookmark", self._bookmark_selected),
            ("Copier chemins", lambda: self._copy_selected("output")),
            ("Copier SHA", lambda: self._copy_selected("sha256")),
            ("Désélectionner", self.file_selection.clear),
        )
        for label, callback in actions:
            button = QToolButton(bar)
            button.setText(label)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch()
        bar.setVisible(False)
        return bar

    def _on_file_selection_changed(self, _change) -> None:
        count = self.file_selection.count
        self.bulk_label.setText(f"{count} fichier(s) sélectionné(s)")
        self.bulk_bar.setVisible(bool(count))

    def _bookmark_selected(self) -> None:
        if self._bookmark_service is None:
            return
        self._bookmark_service.add_many(BookmarkKey("file", file_id) for file_id in self.file_selection.selected_ids())

    def _copy_selected(self, field: str) -> None:
        values = []
        for file_id in self.file_selection.selected_ids():
            record = self._model.record_for_file_id(file_id)
            value = record.get(field) if record is not None else None
            if value:
                values.append(str(value))
        QApplication.clipboard().setText("\n".join(values))

    def load_events(self) -> None:
        if self._loaded:
            return
        with performance.operation("TimelineView", "start_build"):
            self._loaded = True
            self._stop_build()
            self._build_generation += 1
            generation = self._build_generation
            self._build_session = self._service.start_build(retain_events=False)
            if self._background_tasks is not None:
                self._background_tasks.start_task(
                    "timeline",
                    "Construction de la Timeline",
                    total=self._service.record_count,
                )
            self._model.set_events([])
            self._proxy.sort(-1)
            self._proxy.setDynamicSortFilter(False)
            self._proxy.set_building(True)
            self._proxy.setSourceModel(None)
            self.table.setUpdatesEnabled(False)
            self._pending_projection_batches.clear()
            self._projection_scheduled = False
            self._worker_completed = False
            self._bulk_projection_active = True
            self._projection_proxy_attached = False
            self._event_types = {}
            thread = QThread(self)
            worker = _TimelineBuildWorker(self._build_session, generation)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.batch_ready.connect(self._append_batch, Qt.ConnectionType.QueuedConnection)
            worker.progress.connect(self._update_build_progress, Qt.ConnectionType.QueuedConnection)
            worker.finalizing.connect(self._begin_finalization, Qt.ConnectionType.QueuedConnection)
            worker.completed.connect(self._finish_build, Qt.ConnectionType.QueuedConnection)
            worker.failed.connect(self._fail_build, Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            self._build_thread = thread
            self._build_worker = worker
            thread.start()

    @Slot(int, object)
    def _append_batch(self, generation: int, events: tuple) -> None:
        if generation != self._build_generation:
            return
        self._pending_projection_batches.append(events)

    @Slot(int, int)
    def _update_build_progress(self, generation: int, current: int) -> None:
        if generation == self._build_generation and self._background_tasks is not None:
            self._background_tasks.update_task("timeline", current=current)

    @Slot(int)
    def _begin_finalization(self, generation: int) -> None:
        if generation == self._build_generation and self._background_tasks is not None:
            self._background_tasks.set_phase("timeline", "Finalisation de la Timeline…")

    @Slot(int)
    def _finish_build(self, generation: int) -> None:
        if generation != self._build_generation:
            return
        self._build_session = None
        self._worker_completed = True
        self._schedule_projection()

    def _schedule_projection(self) -> None:
        if self._projection_scheduled:
            return
        self._projection_scheduled = True
        QTimer.singleShot(0, self._project_next_batch)

    def _project_next_batch(self) -> None:
        self._projection_scheduled = False
        if self._pending_projection_batches:
            events = self._pending_projection_batches.popleft()
            with performance.operation("TimelineView", "project_checkpoint"):
                self._model.append_events(events)
                for event in events:
                    self._event_types.setdefault(event.event_type.identifier, event.event_type)
                self._attach_projection_proxy()
            self._schedule_projection()
            return
        if self._worker_completed:
            self._finish_projection()

    def _finish_projection(self) -> None:
        if not self._bulk_projection_active:
            return
        self._attach_projection_proxy()
        self._proxy.setDynamicSortFilter(True)
        self._proxy.set_building(False)
        self._bulk_projection_active = False
        self._build_worker = None
        self._build_thread = None
        for identifier, event_type in sorted(self._event_types.items()):
            self.event_type.addItem(event_type.label, identifier)
        if self._pending_event_type:
            index = self.event_type.findData(self._pending_event_type)
            if index >= 0:
                self.event_type.setCurrentIndex(index)
            self._pending_event_type = ""
        if self._pending_sort_state is not None:
            column, order = self._pending_sort_state
            if self._is_initial_chronological_sort(column, order):
                self._set_initial_sort_indicator()
            else:
                self.table.sortByColumn(column, order)
            self._pending_sort_state = None
        else:
            self._set_initial_sort_indicator()
        if self._background_tasks is not None:
            self._background_tasks.finish_task("timeline")

    def _attach_projection_proxy(self) -> None:
        if self._projection_proxy_attached:
            return
        self._proxy.setSourceModel(self._model)
        self.table.setUpdatesEnabled(True)
        self.table.viewport().update()
        self._projection_proxy_attached = True

    @Slot(int, str)
    def _fail_build(self, generation: int, _message: str) -> None:
        if generation != self._build_generation:
            return
        self._build_session = None
        self._build_worker = None
        self._build_thread = None
        self._pending_projection_batches.clear()
        self._projection_scheduled = False
        self._worker_completed = False
        if self._bulk_projection_active:
            self._attach_projection_proxy()
            self._bulk_projection_active = False
        self._proxy.setDynamicSortFilter(True)
        self._proxy.set_building(False)
        if self._background_tasks is not None:
            self._background_tasks.finish_task("timeline", cancelled=True)

    def _stop_build(self) -> None:
        if self._build_worker is not None:
            self._build_worker.cancel()
        self._pending_projection_batches.clear()
        self._projection_scheduled = False
        self._worker_completed = False
        if self._bulk_projection_active:
            self._attach_projection_proxy()
            self._bulk_projection_active = False
        self._build_worker = None
        self._build_thread = None
        self._build_session = None
        if self._background_tasks is not None:
            self._background_tasks.finish_task("timeline", cancelled=True)

    def reset_events(self) -> None:
        self._loaded = False
        self._build_generation += 1
        self._stop_build()
        self._pending_sort_state = None
        self._proxy.setDynamicSortFilter(True)
        self._proxy.set_building(False)
        self._model.set_events(())
        self.event_type.clear()
        self.event_type.addItem("Tous les événements", "")

    def restore_filter_state(self, search: str, category: str, event_type: str, grouping: str = "Fichier") -> None:
        """Restaure un workspace sans déclencher une construction Timeline."""
        self._pending_event_type = event_type
        self.search.setText(search)
        category_index = self.category.findData(category)
        if category_index >= 0:
            self.category.setCurrentIndex(category_index)
        event_index = self.event_type.findData(event_type)
        if event_index >= 0:
            self.event_type.setCurrentIndex(event_index)
            self._pending_event_type = ""

    def restore_sort_state(self, column: int, order: Qt.SortOrder) -> None:
        """Diffère le tri tant que la construction paresseuse n'est pas finie."""
        self._pending_sort_state = column, order
        if self._loaded and self._build_worker is None:
            if self._is_initial_chronological_sort(column, order):
                self._proxy.sort(-1)
                self._set_initial_sort_indicator()
            else:
                self.table.sortByColumn(column, order)
            self._pending_sort_state = None

    @staticmethod
    def _is_initial_chronological_sort(column: int, order: Qt.SortOrder) -> bool:
        return column == 1 and order == Qt.SortOrder.AscendingOrder

    def _set_initial_sort_indicator(self) -> None:
        """Show the chronological source order without asking the proxy to sort it again."""
        header = self.table.header()
        signals_blocked = header.blockSignals(True)
        try:
            header.setSortIndicator(1, Qt.SortOrder.AscendingOrder)
        finally:
            header.blockSignals(signals_blocked)

    def _apply_filters(self) -> None:
        self._proxy.set_filters(
            self.search.text(), str(self.category.currentData() or ""), str(self.event_type.currentData() or "")
        )

    def _toggle_header_selection(self, section: int) -> None:
        if section != TimelineTableModel.SELECTION_COLUMN:
            return
        visible_ids = self._visible_file_ids()
        if visible_ids and all(self.file_selection.contains(file_id) for file_id in visible_ids):
            self.file_selection.deselect_many(visible_ids)
        else:
            self.file_selection.select_many(visible_ids)

    def _visible_file_ids(self) -> tuple[str, ...]:
        file_ids: list[str] = []
        for row in range(self._proxy.rowCount()):
            source = self._proxy.mapToSource(self._proxy.index(row, TimelineTableModel.SELECTION_COLUMN))
            file_id = self._model.file_id_for_index(source)
            if file_id is not None:
                file_ids.append(file_id)
        return tuple(file_ids)

    def _activate_index(self, index) -> None:
        if self._proxy.is_file_index(index):
            self.table.setExpanded(index, not self.table.isExpanded(index))
            return
        event = self._proxy.event_for_index(index)
        if event is not None:
            self.event_activated.emit(event)

    def set_investigation_presence_lookup(self, lookup: Callable[[object], bool] | None) -> None:
        self._investigation_presence_lookup = lookup
        self._model.set_investigation_lookup(lookup)

    def _show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        event = self._proxy.event_for_index(index) if index.isValid() else None
        if event is None:
            return
        self.table.setCurrentIndex(index)
        self._context_menu_for_event(event).exec(self.table.viewport().mapToGlobal(position))

    def _context_menu_for_event(self, event) -> QMenu:
        menu = QMenu(self.table)
        append_investigation_actions(
            menu,
            is_present=bool(self._investigation_presence_lookup and self._investigation_presence_lookup(event)),
            edit_evidence=lambda: self.investigation_item_requested.emit(event),
        )
        return menu

    def _select_index(self, current, _previous) -> None:
        """Publie la sélection simple, sans imposer de navigation entre onglets."""
        event = self._proxy.event_for_index(current)
        if event is not None:
            self.event_selected.emit(event)

    def _copy_selection(self) -> None:
        index = self.table.currentIndex()
        if index.isValid():
            from PySide6.QtWidgets import QApplication

            if index.column() in {
                TimelineTableModel.SELECTION_COLUMN,
                TimelineTableModel.BOOKMARK_COLUMN,
                TimelineTableModel.INVESTIGATION_COLUMN,
            }:
                event = self._proxy.event_for_index(index)
                resolved = self._entity_resolver.resolve(event) if event is not None else None
                record = resolved.file_record if resolved is not None and resolved.is_file else None
                value = record.get("name") if record is not None else ""
            else:
                value = index.data(Qt.ItemDataRole.DisplayRole)
            QApplication.clipboard().setText(str(value or ""))

    def event_for_id(self, event_id: str):
        """Lookup public injecté au résolveur canonique, sans logique de conversion UI."""
        return self._model.event_for_id(event_id)
