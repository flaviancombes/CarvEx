"""Projections Qt en lecture seule des corrélations forensic persistées."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from time import perf_counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from metadata.correlation import MetadataCorrelation, MetadataCorrelationIndex, MetadataCorrelationType
from utils import performance

_ANOMALY_TYPES = frozenset(
    {
        MetadataCorrelationType.DATES_INCONSISTENT,
        MetadataCorrelationType.TIMEZONES_INCONSISTENT,
        MetadataCorrelationType.ORIENTATION_INCONSISTENT,
        MetadataCorrelationType.RESOLUTION_INCONSISTENT,
        MetadataCorrelationType.XMP_WITHOUT_SOFTWARE,
        MetadataCorrelationType.GPS_WITHOUT_TIMESTAMP,
        MetadataCorrelationType.THUMBNAIL_WITHOUT_EXIF,
        MetadataCorrelationType.ICC_WITHOUT_COLORSPACE,
    }
)

_TYPE_LABELS = {
    MetadataCorrelationType.SAME_DEVICE: "Même appareil",
    MetadataCorrelationType.SAME_LENS: "Même objectif",
    MetadataCorrelationType.SAME_SOFTWARE: "Même logiciel",
    MetadataCorrelationType.SAME_AUTHOR: "Même auteur",
    MetadataCorrelationType.SAME_COPYRIGHT: "Même copyright",
    MetadataCorrelationType.SAME_GPS: "Même GPS",
    MetadataCorrelationType.NEARBY_GPS: "GPS proche",
    MetadataCorrelationType.SAME_ORIGIN_DIRECTORY: "Même dossier d'origine",
    MetadataCorrelationType.SAME_EXIF_THUMBNAIL: "Même miniature EXIF",
    MetadataCorrelationType.SAME_ICC_PROFILE: "Même profil ICC",
    MetadataCorrelationType.SAME_MAKER_NOTES: "Même MakerNotes",
    MetadataCorrelationType.DATES_INCONSISTENT: "Date incohérente",
    MetadataCorrelationType.TIMEZONES_INCONSISTENT: "Fuseau incohérent",
    MetadataCorrelationType.ORIENTATION_INCONSISTENT: "Orientation incohérente",
    MetadataCorrelationType.RESOLUTION_INCONSISTENT: "Résolution incohérente",
    MetadataCorrelationType.XMP_WITHOUT_SOFTWARE: "XMP sans logiciel",
    MetadataCorrelationType.GPS_WITHOUT_TIMESTAMP: "GPS sans date",
    MetadataCorrelationType.THUMBNAIL_WITHOUT_EXIF: "Miniature sans EXIF",
    MetadataCorrelationType.ICC_WITHOUT_COLORSPACE: "ICC suspect",
}


def correlation_label(correlation_type: MetadataCorrelationType) -> str:
    """Libellé stable, indépendant des identifiants techniques persistés."""
    return _TYPE_LABELS[correlation_type]


class CorrelationFilterPanel(QGroupBox):
    """Filtre les ``file_id`` depuis un index de corrélations déjà construit."""

    matches_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Filtres corrélations", parent)
        self._index: MetadataCorrelationIndex | None = None
        self._all_file_ids: frozenset[str] = frozenset()
        self._files_by_type: dict[MetadataCorrelationType, frozenset[str]] = {}
        self._tokens: dict[str, frozenset[str]] = {}
        self._scope: frozenset[str] | None = None
        self._type_checks: dict[MetadataCorrelationType, QCheckBox] = {}

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.correlated_only = QCheckBox("Fichiers corrélés", self)
        self.anomalies_only = QCheckBox("Anomalies", self)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Rechercher dans les corrélations…")
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.correlated_only)
        top.addWidget(self.anomalies_only)
        top.addWidget(self.search, 1)
        layout.addLayout(top)
        self.type_container = QWidget(self)
        self.type_layout = QHBoxLayout(self.type_container)
        self.type_layout.setContentsMargins(0, 0, 0, 0)
        self.type_layout.setSpacing(8)
        layout.addWidget(self.type_container)
        self.correlated_only.toggled.connect(self._emit_matches)
        self.anomalies_only.toggled.connect(self._emit_matches)
        self.search.textChanged.connect(self._emit_matches)
        self.setVisible(False)

    def set_index(self, index: MetadataCorrelationIndex | None) -> None:
        """Construit une projection locale une seule fois, sans moteur ni Store."""
        started_at = perf_counter() if performance.ENABLED else 0.0
        correlation_count = 0
        self._index = index
        self._all_file_ids = frozenset()
        self._files_by_type = {}
        self._tokens = {}
        self._scope = None
        self._clear_type_checks()
        if index is not None:
            by_type: dict[MetadataCorrelationType, set[str]] = defaultdict(set)
            tokens: dict[str, set[str]] = defaultdict(set)
            all_file_ids: set[str] = set()
            for correlation in index.all():
                correlation_count += 1
                file_ids = set(correlation.file_ids)
                all_file_ids.update(file_ids)
                by_type[correlation.correlation_type].update(file_ids)
                for token in self._tokens_for(correlation):
                    tokens[token].update(file_ids)
            self._all_file_ids = frozenset(all_file_ids)
            self._files_by_type = {kind: frozenset(file_ids) for kind, file_ids in by_type.items()}
            self._tokens = {token: frozenset(file_ids) for token, file_ids in tokens.items()}
            self._create_type_checks()
        self.setVisible(bool(self._all_file_ids))
        if performance.ENABLED:
            performance.LOGGER.info(
                "[CorrelationsFilter] projection duration_ms=%.2f correlations_examined=%d "
                "correlated_files=%d types=%d tokens=%d",
                (perf_counter() - started_at) * 1000,
                correlation_count,
                len(self._all_file_ids),
                len(self._files_by_type),
                len(self._tokens),
            )
        self._emit_matches()

    def show_related_to(self, file_id: str) -> None:
        """Affiche les groupes déjà associés à une preuve, sans requête de métadonnées."""
        if self._index is None:
            return
        related = {member for correlation in self._index.for_file(file_id) for member in correlation.file_ids}
        self._scope = frozenset(related)
        self.correlated_only.setChecked(True)
        self._emit_matches()

    def search_matches(self, text: str) -> frozenset[str]:
        """Résout une recherche globale depuis le petit index UI déjà construit."""
        tokens = tuple(token for token in re.findall(r"[\w]+", text.casefold()) if token)
        if not tokens:
            return frozenset()
        matches = set(self._all_file_ids)
        for token in tokens:
            matches.intersection_update(self._tokens.get(token, ()))
        return frozenset(matches)

    def state(self) -> dict[str, str]:
        return {
            "correlated": str(self.correlated_only.isChecked()),
            "anomalies": str(self.anomalies_only.isChecked()),
            "search": self.search.text(),
            "types": ",".join(kind.value for kind, check in self._type_checks.items() if check.isChecked()),
        }

    def restore_state(self, state: dict[str, str]) -> None:
        self.correlated_only.setChecked(state.get("correlated") == "True")
        self.anomalies_only.setChecked(state.get("anomalies") == "True")
        self.search.setText(state.get("search", ""))
        selected = frozenset(filter(None, state.get("types", "").split(",")))
        for kind, check in self._type_checks.items():
            check.setChecked(kind.value in selected)

    def clear_scope(self) -> None:
        if self._scope is not None:
            self._scope = None
            self._emit_matches()

    def _create_type_checks(self) -> None:
        for correlation_type in sorted(self._files_by_type, key=lambda item: item.value):
            check = QCheckBox(correlation_label(correlation_type), self.type_container)
            check.toggled.connect(self._emit_matches)
            self.type_layout.addWidget(check)
            self._type_checks[correlation_type] = check
        self.type_layout.addStretch()

    def _clear_type_checks(self) -> None:
        while self.type_layout.count():
            item = self.type_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._type_checks.clear()

    def _emit_matches(self, *_args) -> None:
        started_at = perf_counter() if performance.ENABLED else 0.0
        if not self._all_file_ids:
            self._log_filter_resolution(started_at, 0, 0, ())
            self.matches_changed.emit(None)
            self._log_filter_action(started_at, None)
            return
        selected_types = {kind for kind, check in self._type_checks.items() if check.isChecked()}
        if self.anomalies_only.isChecked():
            selected_types.update(_ANOMALY_TYPES.intersection(self._files_by_type))
        tokens = tuple(token for token in re.findall(r"[\w]+", self.search.text().casefold()) if token)
        if not (self.correlated_only.isChecked() or selected_types or tokens or self._scope is not None):
            self._log_filter_resolution(started_at, 0, 0, tokens)
            self.matches_changed.emit(None)
            self._log_filter_action(started_at, None)
            return
        if selected_types:
            matches: frozenset[str] | set[str] = frozenset().union(
                *(self._files_by_type.get(correlation_type, ()) for correlation_type in selected_types)
            )
        else:
            # Cas courant : l'index local représente déjà exactement le résultat.
            # Ne pas recopier potentiellement plusieurs centaines de milliers d'identifiants.
            matches = self._all_file_ids
        for token in tokens:
            matches = matches.intersection(self._tokens.get(token, ()))
        if self._scope is not None:
            matches = matches.intersection(self._scope)
        self._log_filter_resolution(started_at, len(matches), len(selected_types), tokens)
        resolved_matches = matches if isinstance(matches, frozenset) else frozenset(matches)
        self.matches_changed.emit(resolved_matches)
        self._log_filter_action(started_at, len(resolved_matches))

    def _log_filter_resolution(
        self,
        started_at: float,
        match_count: int,
        selected_type_count: int,
        tokens: tuple[str, ...],
    ) -> None:
        """Journalise le seul travail de résolution local, sans mesurer le proxy Qt."""
        if not performance.ENABLED:
            return
        performance.LOGGER.info(
            "[CorrelationsFilter] resolve_state duration_ms=%.2f correlations_indexed=%d "
            "correlated_files=%d matches=%d selected_types=%d tokens=%d scoped=%s",
            (perf_counter() - started_at) * 1000,
            len(self._files_by_type),
            len(self._all_file_ids),
            match_count,
            selected_type_count,
            len(tokens),
            self._scope is not None,
        )

    @staticmethod
    def _log_filter_action(started_at: float, match_count: int | None) -> None:
        """Mesure le chemin synchrone clic → proxy, hors tâches Qt différées."""
        if performance.ENABLED:
            performance.LOGGER.info(
                "[CorrelationsFilter] action duration_ms=%.2f emitted_matches=%s",
                (perf_counter() - started_at) * 1000,
                match_count,
            )

    @staticmethod
    def _tokens_for(correlation: MetadataCorrelation) -> frozenset[str]:
        return frozenset(
            re.findall(
                r"[\w]+",
                f"{correlation_label(correlation.correlation_type)} {correlation.key} {correlation.summary}".casefold(),
            )
        )


class CorrelationPanel(QGroupBox):
    """Badges et arborescence de corrélations pour le fichier sélectionné."""

    file_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Corrélations", parent)
        self._index: MetadataCorrelationIndex | None = None
        self._label_for_file: Callable[[str], str] = lambda file_id: file_id
        layout = QVBoxLayout(self)
        self.badges = QWidget(self)
        self.badges_layout = QHBoxLayout(self.badges)
        self.badges_layout.setContentsMargins(0, 0, 0, 0)
        self.badges_layout.setSpacing(6)
        layout.addWidget(self.badges)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self.tree)
        self.hide()

    def set_index(
        self, index: MetadataCorrelationIndex | None, label_for_file: Callable[[str], str] | None = None
    ) -> None:
        self._index = index
        if label_for_file is not None:
            self._label_for_file = label_for_file

    def set_file(self, file_id: str | None) -> None:
        self.tree.clear()
        self._clear_badges()
        if file_id is None or self._index is None:
            self.hide()
            return
        correlations = self._index.for_file(file_id)
        if not correlations:
            self.hide()
            return
        grouped: dict[MetadataCorrelationType, list[MetadataCorrelation]] = defaultdict(list)
        for correlation in correlations:
            grouped[correlation.correlation_type].append(correlation)
        for correlation_type in sorted(grouped, key=lambda item: item.value):
            correlations_for_type = grouped[correlation_type]
            badge = QLabel(f"{correlation_label(correlation_type)} ({len(correlations_for_type)})", self.badges)
            badge.setObjectName("artifactBadge")
            if correlation_type in _ANOMALY_TYPES:
                badge.setProperty("severity", "warning")
            self.badges_layout.addWidget(badge)
            type_item = QTreeWidgetItem([correlation_label(correlation_type)])
            self.tree.addTopLevelItem(type_item)
            for correlation in correlations_for_type:
                group_item = QTreeWidgetItem([correlation.summary])
                type_item.addChild(group_item)
                for related_file_id in correlation.file_ids:
                    child = QTreeWidgetItem([self._label_for_file(related_file_id)])
                    child.setData(0, Qt.ItemDataRole.UserRole, related_file_id)
                    group_item.addChild(child)
            type_item.setExpanded(True)
        self.badges_layout.addStretch()
        self.show()

    def _open_item(self, item: QTreeWidgetItem, _column: int) -> None:
        file_id = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(file_id, str):
            self.file_requested.emit(file_id)

    def _clear_badges(self) -> None:
        while self.badges_layout.count():
            item = self.badges_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def expanded_types(self) -> tuple[str, ...]:
        labels: list[str] = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.isExpanded():
                labels.append(item.text(0))
        return tuple(labels)

    def restore_expanded_types(self, labels: tuple[str, ...]) -> None:
        wanted = frozenset(labels)
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None:
                item.setExpanded(item.text(0) in wanted)
