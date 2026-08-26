"""Proxy Qt combinant recherche textuelle, catégories et tri natif."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from threading import current_thread
from time import perf_counter
from typing import Protocol

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, QTimer

from core.duplicates import DuplicateIndex
from metadata.index import MetadataIndex
from metadata.query import MetadataQuery
from models.file_table_model import FileTableModel
from utils import performance


@dataclass(slots=True)
class _CategoryFilterProfile:
    previous_category: str
    category: str
    source_rows: int
    started_at: float
    thread_name: str
    filter_calls: int = 0
    category_rejections: int = 0
    other_rejections: int = 0
    accepted_rows: int = 0
    sort_calls: int = 0
    model_resets: int = 0
    layout_changes: int = 0
    data_changes: int = 0


class ArtifactCacheLookup(Protocol):
    """Contrat de lecture : il ne déclenche jamais de calcul d'artefacts."""

    def cached_for(self, file_record: Mapping[str, object]) -> tuple[object, ...] | None: ...


class FileFilterProxyModel(QSortFilterProxyModel):
    """Filtre les enregistrements du modèle source sans créer de liste dérivée."""

    SEARCH_FIELDS = FileTableModel.SEARCH_FIELDS

    def __init__(
        self,
        artifact_cache: ArtifactCacheLookup | None = None,
        duplicate_index: DuplicateIndex | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._search_text = ""
        self._category = ""
        self._artifact_filter = ""
        self._artifact_cache = artifact_cache
        self._duplicate_index = duplicate_index or DuplicateIndex()
        self._duplicates_only = False
        self._artifact_matches: dict[str, bool] = {}
        self._metadata_index: MetadataIndex | None = None
        self._metadata_matches: frozenset[str] | None = None
        self._metadata_query: MetadataQuery | None = None
        self._metadata_sort_identifier = ""
        self._correlation_matches: frozenset[str] | None = None
        self._universal_matches: frozenset[str] = frozenset()
        self._category_profile: _CategoryFilterProfile | None = None
        self.setDynamicSortFilter(True)
        self.setSortLocaleAware(True)
        self.modelReset.connect(self._record_model_reset)
        self.layoutChanged.connect(self._record_layout_change)
        self.dataChanged.connect(self._record_data_change)

    def set_search_text(self, text: str) -> None:
        normalized = text.casefold().strip()
        if normalized == self._search_text:
            return
        self.beginFilterChange()
        self._search_text = normalized
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_universal_search(self, text: str, matches: frozenset[str]) -> None:
        normalized = text.casefold().strip()
        if normalized == self._search_text and matches == self._universal_matches:
            return
        self.beginFilterChange()
        self._search_text = normalized
        self._universal_matches = matches
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_category(self, category: str) -> None:
        if category == self._category:
            return
        self._finish_category_profile()
        model = self.sourceModel()
        self._category_profile = (
            _CategoryFilterProfile(
                previous_category=self._category,
                category=category,
                source_rows=model.rowCount() if isinstance(model, FileTableModel) else 0,
                started_at=perf_counter(),
                thread_name=current_thread().name,
            )
            if performance.ENABLED
            else None
        )
        self.beginFilterChange()
        self._category = category
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        if self._category_profile is not None:
            QTimer.singleShot(0, self._schedule_category_profile_finish)

    def set_artifact_filter(self, artifact_filter: str) -> None:
        if artifact_filter == self._artifact_filter:
            return
        self.beginFilterChange()
        self._artifact_filter = artifact_filter
        self._artifact_matches.clear()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_duplicates_only(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._duplicates_only:
            return
        self.beginFilterChange()
        self._duplicates_only = enabled
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_metadata_index(self, index: MetadataIndex | None) -> None:
        """Attach a read-only persistent index; no manager or provider is involved."""
        self._metadata_index = index
        self.set_metadata_query(None)

    def set_metadata_query(self, query: MetadataQuery | None) -> None:
        self._metadata_query = query
        self.refresh_metadata_query()

    def refresh_metadata_query(self) -> None:
        query = self._metadata_query
        if query is None or (not query.predicates and not query.filters and not query.text.strip()):
            matches = None
        else:
            model = self.sourceModel()
            candidates = model.file_ids() if isinstance(model, FileTableModel) else ()
            matches = (
                query.execute(self._metadata_index, candidates) if self._metadata_index is not None else frozenset()
            )
        if matches == self._metadata_matches:
            return
        self.beginFilterChange()
        self._metadata_matches = matches
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_metadata_sort_identifier(self, identifier: str) -> None:
        identifier = identifier.casefold().strip()
        if identifier == self._metadata_sort_identifier:
            return
        self._metadata_sort_identifier = identifier
        self.invalidate()
        self.sort(self.sortColumn(), self.sortOrder())

    def set_correlation_matches(self, matches: frozenset[str] | None) -> None:
        if matches == self._correlation_matches:
            return
        self.beginFilterChange()
        self._correlation_matches = matches
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    @property
    def artifact_filter(self) -> str:
        return self._artifact_filter

    def refresh_artifact_rows(self, file_ids: tuple[str, ...] | list[str]) -> None:
        """Oublie uniquement les résultats de cache changés avant le ``dataChanged`` source."""
        for file_id in file_ids:
            self._artifact_matches.pop(file_id, None)

    def clear_artifact_matches(self) -> None:
        self._artifact_matches.clear()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        profile = self._category_profile
        if profile is not None:
            profile.filter_calls += 1
        model = self.sourceModel()
        if not isinstance(model, FileTableModel):
            if profile is not None:
                profile.other_rejections += 1
            return False
        filter_row = model.filter_row_at(source_row)
        record = model.record_at(source_row)
        if filter_row is None or record is None:
            if profile is not None:
                profile.other_rejections += 1
            return False
        if self._category and filter_row.category != self._category:
            if profile is not None:
                profile.category_rejections += 1
            return False
        if self._duplicates_only and (
            filter_row.file_id is None or not self._duplicate_index.is_duplicate(filter_row.file_id)
        ):
            if profile is not None:
                profile.other_rejections += 1
            return False
        if self._metadata_matches is not None and filter_row.file_id not in self._metadata_matches:
            if profile is not None:
                profile.other_rejections += 1
            return False
        if self._correlation_matches is not None and filter_row.file_id not in self._correlation_matches:
            if profile is not None:
                profile.other_rejections += 1
            return False
        if self._artifact_filter:
            if self._artifact_filter.startswith("image.") and not filter_row.is_image:
                if profile is not None:
                    profile.other_rejections += 1
                return False
            if self._artifact_cache is None:
                if profile is not None:
                    profile.other_rejections += 1
                return False
            if not self._matches_artifact(filter_row.file_id, record):
                if profile is not None:
                    profile.other_rejections += 1
                return False
        if not self._search_text:
            if profile is not None:
                profile.accepted_rows += 1
            return True
        accepted = filter_row.file_id in self._universal_matches or any(
            self._search_text in value for value in filter_row.search_fields
        )
        if profile is not None:
            if accepted:
                profile.accepted_rows += 1
            else:
                profile.other_rejections += 1
        return accepted

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        if self._category_profile is not None:
            self._category_profile.sort_calls += 1
        if self._metadata_sort_identifier:
            model = self.sourceModel()
            if isinstance(model, FileTableModel) and self._metadata_index is not None:
                left_id = model.file_id_at(left.row())
                right_id = model.file_id_at(right.row())
                if left_id is not None and right_id is not None:
                    return self._metadata_index.sort_key(
                        left_id, self._metadata_sort_identifier
                    ) < self._metadata_index.sort_key(right_id, self._metadata_sort_identifier)
        if left.column() == FileTableModel.SIZE_COLUMN:
            model = self.sourceModel()
            if isinstance(model, FileTableModel):
                left_size = model.numeric_size_at(left.row())
                right_size = model.numeric_size_at(right.row())
                if left_size is not None and right_size is not None:
                    return left_size < right_size
        if left.column() == FileTableModel.DUPLICATE_COUNT_COLUMN:
            model = self.sourceModel()
            if isinstance(model, FileTableModel):
                return model.duplicate_count_at(left.row()) < model.duplicate_count_at(right.row())
        if left.column() == FileTableModel.CORRELATIONS_COLUMN:
            model = self.sourceModel()
            if isinstance(model, FileTableModel):
                return model.correlation_count_at(left.row()) < model.correlation_count_at(right.row())
        return super().lessThan(left, right)

    def _matches_artifact(self, file_id: str | None, record: Mapping[str, object]) -> bool:
        if file_id is not None and file_id in self._artifact_matches:
            return self._artifact_matches[file_id]
        artifacts = self._artifact_cache.cached_for(record) if self._artifact_cache is not None else None
        result = bool(
            artifacts is not None
            and any(
                getattr(artifact, "matches", lambda _filter: False)(self._artifact_filter) for artifact in artifacts
            )
        )
        if file_id is not None:
            self._artifact_matches[file_id] = result
        return result

    def _record_model_reset(self) -> None:
        if self._category_profile is not None:
            self._category_profile.model_resets += 1

    def _record_layout_change(self) -> None:
        if self._category_profile is not None:
            self._category_profile.layout_changes += 1

    def _record_data_change(self, *_args) -> None:
        if self._category_profile is not None:
            self._category_profile.data_changes += 1

    def _schedule_category_profile_finish(self) -> None:
        QTimer.singleShot(0, self._finish_category_profile)

    def _finish_category_profile(self) -> None:
        profile = self._category_profile
        if profile is None:
            return
        self._category_profile = None
        performance.LOGGER.info(
            "[Catégorie] %r -> %r duration_ms=%.2f thread=%s source_rows=%d "
            "filter_calls=%d accepted=%d category_rejections=%d other_rejections=%d "
            "sort_calls=%d model_reset=%d layout_changed=%d data_changed=%d "
            "metadata_filter_active=%s correlation_filter_active=%s search_active=%s artifact_filter_active=%s",
            profile.previous_category,
            profile.category,
            (perf_counter() - profile.started_at) * 1000,
            profile.thread_name,
            profile.source_rows,
            profile.filter_calls,
            profile.accepted_rows,
            profile.category_rejections,
            profile.other_rejections,
            profile.sort_calls,
            profile.model_resets,
            profile.layout_changes,
            profile.data_changes,
            self._metadata_matches is not None,
            self._correlation_matches is not None,
            bool(self._search_text),
            bool(self._artifact_filter),
        )
