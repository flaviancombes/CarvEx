"""Projections Qt des corrélations déjà persistées, sans extraction ni I/O."""

from __future__ import annotations

from metadata.base import MetadataCategory, MetadataField
from metadata.correlation import MetadataCorrelation, MetadataCorrelationIndex, MetadataCorrelationType
from metadata.index import MetadataIndex
from models.file_table_model import FileTableModel
from ui.correlation_panel import CorrelationPanel
from ui.file_table import FileTable

FILE_1 = "00000000-0000-4000-8000-000000000001"
FILE_2 = "00000000-0000-4000-8000-000000000002"
FILE_3 = "00000000-0000-4000-8000-000000000003"
FILE_4 = "00000000-0000-4000-8000-000000000004"


def _correlation(kind: MetadataCorrelationType, key: str, file_ids: tuple[str, ...]) -> MetadataCorrelation:
    return MetadataCorrelation(f"{kind.value}-{key}", kind, file_ids, key, f"{kind.value}: {key}")


def _index() -> MetadataCorrelationIndex:
    return MetadataCorrelationIndex(
        (
            _correlation(MetadataCorrelationType.SAME_DEVICE, "Canon", (FILE_1, FILE_2)),
            _correlation(MetadataCorrelationType.SAME_GPS, "48.85,2.35", (FILE_1, FILE_3)),
            _correlation(MetadataCorrelationType.DATES_INCONSISTENT, FILE_3, (FILE_3,)),
        )
    )


def _records():
    return (
        {"file_id": FILE_1, "name": "one.jpg", "category": "Images"},
        {"file_id": FILE_2, "name": "two.jpg", "category": "Images"},
        {"file_id": FILE_3, "name": "three.jpg", "category": "Images"},
        {"file_id": FILE_4, "name": "four.jpg", "category": "Images"},
    )


def test_correlation_column_exposes_persisted_count_and_numeric_sort(qapp):
    table = FileTable()
    table.set_files(_records())
    summaries: list[dict[str, int]] = []
    table.correlation_summary_changed.connect(summaries.append)
    table.set_correlation_index(_index())

    column = FileTableModel.CORRELATIONS_COLUMN
    assert table._source_model.data(table._source_model.index(0, column)) == 2
    assert table._source_model.data(table._source_model.index(1, column)) == 1
    table._proxy_model.sort(column)

    assert table._proxy_model.index(0, 3).data() == "four.jpg"
    assert table._proxy_model.index(3, column).data() == 2
    assert summaries[-1] == {"files": 3, "anomalies": 1, "gps": 1, "devices": 1}
    assert "Voir tous les fichiers corrélés" in [
        action.text() for action in table._context_menu_for_record(_records()[0]).actions()
    ]


def test_correlation_filter_search_and_context_scope_use_only_cached_index(qapp):
    table = FileTable()
    table.set_files(_records())
    table.set_correlation_index(_index())

    table.correlation_filters.correlated_only.setChecked(True)
    assert table.visible_file_count == 3
    assert len(table.correlation_filters._type_checks) == 3
    table.correlation_filters.search.setText("Canon")
    assert table.visible_file_count == 2
    table.correlation_filters.search.clear()
    table.show_correlated_files(_records()[0])

    assert table.visible_file_count == 3


def test_correlation_panel_displays_badges_and_publishes_file_navigation(qtbot):
    panel = CorrelationPanel()
    qtbot.addWidget(panel)
    requested: list[str] = []
    panel.file_requested.connect(requested.append)
    panel.set_index(_index(), lambda file_id: {FILE_1: "one.jpg", FILE_2: "two.jpg", FILE_3: "three.jpg"}[file_id])
    panel.set_file(FILE_1)

    assert panel.isVisible()
    assert panel.tree.topLevelItemCount() == 2
    file_item = panel.tree.topLevelItem(0).child(0).child(1)
    panel._open_item(file_item, 0)

    assert requested == [FILE_2]


def test_correlation_counts_handle_a_simulated_three_hundred_thousand_file_group_without_recalculation(qapp):
    file_ids = tuple(f"00000000-0000-4000-8000-{number:012d}" for number in range(300_000))
    correlation = _correlation(MetadataCorrelationType.SAME_DEVICE, "Canon", file_ids)

    class _PersistentIndex:
        @staticmethod
        def all():
            return (correlation,)

    model = FileTableModel(records=({"file_id": file_ids[-1], "name": "last.jpg"},))
    model.set_correlation_index(_PersistentIndex())

    assert model.correlation_count_at(0) == 1


def test_universal_search_uses_only_existing_metadata_and_correlation_indexes(qapp):
    table = FileTable()
    table.set_files(_records())
    metadata = MetadataIndex()
    metadata.add(
        FILE_2,
        (MetadataField("exif.model", MetadataCategory.EXIF, "Modèle", "Nikon", source="test"),),
    )
    table.set_metadata_index(metadata)
    table.set_correlation_index(_index())

    table.search_field.setText("Nikon")
    assert table.visible_file_count == 1
    assert table.record_for_index(table._proxy_model.index(0, 0))["file_id"] == FILE_2
    table.search_field.setText("Canon")
    assert table.visible_file_count == 2


def test_selection_is_restored_by_file_id_after_filter_changes(qtbot):
    table = FileTable()
    qtbot.addWidget(table)
    table.set_files(_records())
    table.select_record(_records()[1])
    table.search_field.setText("two")
    qtbot.wait(10)

    assert table.record_for_index(table.view.currentIndex())["file_id"] == FILE_2
    table.search_field.clear()
    qtbot.wait(10)
    assert table.record_for_index(table.view.currentIndex())["file_id"] == FILE_2


def test_tooltip_uses_record_and_indexed_values_without_metadata_manager(qapp):
    model = FileTableModel(records=(_records()[0],))
    metadata = MetadataIndex()
    metadata.add(
        FILE_1,
        (
            MetadataField("exif.model", MetadataCategory.EXIF, "Modèle", "Canon", source="test"),
            MetadataField("exif.gps.latitude", MetadataCategory.EXIF, "Latitude", 48.8, source="test"),
        ),
    )
    model.set_metadata_index(metadata)

    tooltip = model.data(model.index(0, 3), role=3)
    assert "Appareil : Canon" in tooltip
    assert "GPS : présent" in tooltip
