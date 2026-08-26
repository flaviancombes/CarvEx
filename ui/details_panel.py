"""Panneau droit d'inspection d'un fichier sélectionné."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from analysis.artifact_classifier import ArtifactClassifier, build_default_classifier
from metadata.correlation import MetadataCorrelationIndex
from metadata.manager import MetadataManager, build_default_manager
from selection.context import SelectionContext
from selection.manager import SelectionManager
from selection.resolver import SelectionResolver
from timeline.manager import TimelineManager
from timeline.manager import build_default_manager as build_timeline_manager
from ui.artifacts_panel import ArtifactsPanel
from ui.correlation_panel import CorrelationPanel
from ui.details_providers import DetailsProvider, DetailsProviderRegistry, FileDetailsProvider
from ui.metadata_panel import MetadataPanel
from ui.preview_panel import PreviewPanel
from ui.theme import Metrics
from ui.timeline_panel import TimelinePanel
from ui.widgets.selectable_text_field import SelectableTextField
from utils.performance import format_byte_size


class DetailsPanel(QScrollArea):
    """Panneau d'aperçu et de métadonnées organisé en sections DFIR."""

    SECTIONS = (
        (
            "Informations",
            (("name", "Nom du fichier"), ("category", "Catégorie"), ("mime", "Type MIME"), ("size", "Taille")),
        ),
        ("Intégrité", (("sha256", "SHA-256"),)),
        (
            "Emplacements",
            (
                ("output", "Chemin exporté"),
                ("source_path", "Chemin PhotoRec"),
                ("source_directory", "Dossier PhotoRec"),
            ),
        ),
    )

    def __init__(
        self,
        metadata_manager: MetadataManager | None = None,
        classifier: ArtifactClassifier | None = None,
        parent=None,
        timeline_manager: TimelineManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("detailsPanel")
        self.setWidgetResizable(True)

        content = QWidget(self)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(
            Metrics.PANEL_MARGIN, Metrics.PANEL_MARGIN, Metrics.PANEL_MARGIN, Metrics.PANEL_MARGIN
        )
        self.content_layout.setSpacing(Metrics.PANEL_SPACING)

        self.title = QLabel("Aucun fichier sélectionné", content)
        self.title.setObjectName("detailsTitle")
        self.title.setWordWrap(True)
        self.content_layout.addWidget(self.title)
        self._file_widgets: list[QWidget] = []
        self._provider_widget: QWidget | None = None
        self._file_extension_widget: QWidget | None = None
        self.correlation_panel = CorrelationPanel(content)
        self.correlation_panel.file_requested.connect(self._publish_correlation_file)
        self.content_layout.addWidget(self.correlation_panel)
        self._file_widgets.append(self.correlation_panel)

        preview_section = QGroupBox("Aperçu", content)
        preview_layout = QVBoxLayout(preview_section)
        preview_layout.setContentsMargins(
            Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING, Metrics.PANEL_SPACING
        )
        self.preview_panel = PreviewPanel(preview_section)
        preview_layout.addWidget(self.preview_panel)
        self.content_layout.addWidget(preview_section)
        self._file_widgets.append(preview_section)

        self._fields: dict[str, SelectableTextField] = {}
        for section_title, fields in self.SECTIONS:
            section = self._create_section(section_title, fields, content)
            self.content_layout.addWidget(section)
            self._file_widgets.append(section)

        self._metadata_manager = metadata_manager or build_default_manager()
        self._classifier = classifier or build_default_classifier()
        self._selection_manager: SelectionManager | None = None
        self._selection_resolver: SelectionResolver | None = None
        self._file_provider: FileDetailsProvider | None = None
        self._providers = DetailsProviderRegistry()
        self.metadata_panel = MetadataPanel(
            cache=self._metadata_manager.cache, parent=content, manager=self._metadata_manager
        )
        self.content_layout.addWidget(self.metadata_panel)
        self._file_widgets.append(self.metadata_panel)
        self.artifacts_panel = ArtifactsPanel(self._metadata_manager, self._classifier, parent=content)
        self.content_layout.addWidget(self.artifacts_panel)
        self._file_widgets.append(self.artifacts_panel)
        self._timeline_manager = timeline_manager or build_timeline_manager(self._metadata_manager)
        self.timeline_panel = TimelinePanel(self._timeline_manager, parent=content)
        self.content_layout.addWidget(self.timeline_panel)
        self._file_widgets.append(self.timeline_panel)

        # Réservé aux futures sections : EXIF, timeline, VirusTotal, hex viewer, etc.
        self.content_layout.addStretch()
        self.setWidget(content)

    def bind_selection(self, manager: SelectionManager, resolver: SelectionResolver) -> None:
        """Abonne le panneau au bus de sélection sans dépendre d'une vue précise."""
        if self._selection_manager is manager and self._selection_resolver is resolver:
            return
        if self._selection_manager is not None:
            try:
                self._selection_manager.selection_changed.disconnect(self.set_context)
            except (RuntimeError, TypeError):
                pass
        self._selection_manager = manager
        self._selection_resolver = resolver
        self._providers.clear()
        self._file_provider = FileDetailsProvider(resolver)
        self._providers.register(self._file_provider)
        manager.selection_changed.connect(self.set_context)
        self.set_context(manager.current)

    def register_provider(self, provider: DetailsProvider) -> None:
        """Ajoute un futur provider sans coupler le panneau aux modules métier."""
        self._providers.register(provider)
        if self._selection_manager is not None and self._selection_manager.current is not None:
            self.set_context(self._selection_manager.current)

    def unregister_provider(self, provider: DetailsProvider) -> None:
        self._providers.unregister(provider)

    def show_provider_widget(self, title: str, widget: QWidget) -> None:
        """Affiche du contenu spécialisé sans coupler le panneau aux modules métier."""
        self._clear_file_extension_widget()
        for file_widget in self._file_widgets:
            file_widget.hide()
        if self._provider_widget is not widget:
            if self._provider_widget is not None:
                self._provider_widget.hide()
            self._provider_widget = widget
            self.content_layout.insertWidget(self.content_layout.count() - 1, widget)
        self.title.setText(title)
        widget.show()

    def populate_file_context(self, context: SelectionContext) -> bool:
        """Réutilise le provider fichier existant pour une sélection composée."""
        if self._file_provider is None or not self._file_provider.supports(context):
            return False
        self._file_provider.populate(self, context)
        return True

    def show_file_extension_widget(self, widget: QWidget) -> None:
        """Ajoute une extension métier avant les données du fichier, sans les dupliquer."""
        if self._file_extension_widget is not widget:
            if self._file_extension_widget is not None:
                self._file_extension_widget.hide()
            self._file_extension_widget = widget
            self.content_layout.insertWidget(1, widget)
        widget.show()

    def current_file_title(self) -> str:
        """Expose le libellé déjà rendu par le provider Fichier."""
        return self.title.text()

    def set_correlation_index(self, index: MetadataCorrelationIndex | None, label_for_file=None) -> None:
        self.correlation_panel.set_index(index, label_for_file)

    def _publish_correlation_file(self, file_id: str) -> None:
        self.publish_context(
            SelectionContext("file", file_id, "metadata_correlations", navigation_hint={"view": "files"})
        )

    def _clear_file_extension_widget(self) -> None:
        if self._file_extension_widget is not None:
            self._file_extension_widget.hide()
        self._file_extension_widget = None

    def clear_provider_widget(self) -> None:
        if self._provider_widget is not None:
            self._provider_widget.hide()
        self._provider_widget = None
        self.set_file(None)

    def publish_context(self, context: SelectionContext) -> None:
        """Permet à un provider de demander une navigation via le bus partagé."""
        if self._selection_manager is not None:
            self._selection_manager.publish(context)

    def set_context(self, context: SelectionContext | None) -> None:
        """Adapte la sélection légère au contrat historique du panneau de détails."""
        if context is None or not self._providers.populate(self, context):
            self.set_file(None)
            return

    def _create_section(self, title: str, fields: Sequence[tuple[str, str]], parent: QWidget) -> QGroupBox:
        section = QGroupBox(title, parent)
        form = QFormLayout(section)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setVerticalSpacing(Metrics.PANEL_SPACING)
        for field, label in fields:
            value_field = SelectableTextField(section)
            self._fields[field] = value_field
            form.addRow(label, value_field)
        return section

    def set_file(self, file_record: Mapping[str, Any] | None) -> None:
        """Met à jour l'aperçu et les métadonnées existantes du rapport."""
        self._clear_file_extension_widget()
        if self._provider_widget is not None:
            self._provider_widget.hide()
            self._provider_widget = None
        for file_widget in self._file_widgets:
            file_widget.show()
        self.preview_panel.set_file(file_record)
        self.metadata_panel.set_file(file_record)
        self.artifacts_panel.set_file(file_record)
        self.timeline_panel.set_file(file_record)
        self.correlation_panel.set_file(None if file_record is None else str(file_record.get("file_id") or "") or None)
        if file_record is None:
            self.title.setText("Aucun fichier sélectionné")
            for field in self._fields.values():
                field.set_value(None)
            return

        self.title.setText(str(file_record.get("name") or "Sans nom"))
        for name, field in self._fields.items():
            value = file_record.get(name)
            field.set_value(format_byte_size(value) if name == "size" else value)
