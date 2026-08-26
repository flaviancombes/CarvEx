"""Provider éditable du DetailsPanel partagé pour les objets Investigation."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.hypothesis import HypothesisConfidence, HypothesisStatus, InvestigationHypothesisId
from investigation.item import InvestigationItemId
from investigation.note import InvestigationNoteId
from investigation.queries import InvestigationQueryService
from investigation.relation import InvestigationRelationId, InvestigationRelationType
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.context import SelectionContext
from ui.details_providers import DetailsPanelHost
from ui.investigation_details_components import (
    InvestigationDetailsEditor,
    InvestigationDetailsNavigation,
    InvestigationJournalRenderer,
    InvestigationMembershipActions,
    InvestigationPreviewBridge,
    InvestigationRelationRenderer,
    InvestigationTargetRenderer,
)
from ui.investigation_dialogs import NoteCreationDialog, RelationCreationDialog


class _MemberNavigationButton(QPushButton):
    """Bouton de membre dont le double-clic est une intention de navigation."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()
        event.accept()


class InvestigationDetailsWidget(QWidget):
    """Éditeur Qt sans accès aux repositories ni aux stores Investigation."""

    deleted = Signal()
    related_selected = Signal(object)

    def __init__(
        self, service: InvestigationService, queries: InvestigationQueryService | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._queries = queries or InvestigationQueryService(service)
        self._editor = InvestigationDetailsEditor(service, self._queries)
        self._targets = InvestigationTargetRenderer(service)
        self._kind: str | None = None
        self._object_id: str | None = None
        self._file_target_id: str | None = None
        self._navigation_hint: dict[str, str] = {}
        self.breadcrumb_label = QLabel("", self)
        self.breadcrumb_label.setWordWrap(True)
        self.breadcrumb_label.setTextFormat(Qt.TextFormat.RichText)
        self.breadcrumb_label.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.breadcrumb_label.linkActivated.connect(self._navigate_breadcrumb)
        self.return_to_container_button = QPushButton("Retour à la Case", self)
        self.return_to_container_button.setVisible(False)
        self._form = QFormLayout()
        self.name_field = QLineEdit(self)
        self.original_name_field = QLineEdit(self)
        self.original_name_field.setReadOnly(True)
        self.description_field = QTextEdit(self)
        self.type_field = QLineEdit(self)
        self.content_field = QTextEdit(self)
        self.confidence_field = QComboBox(self)
        self.confidence_field.addItem("Faible", HypothesisConfidence.LOW.value)
        self.confidence_field.addItem("Moyenne", HypothesisConfidence.MEDIUM.value)
        self.confidence_field.addItem("Élevée", HypothesisConfidence.HIGH.value)
        self.status_field = QComboBox(self)
        self.status_field.addItem("Ouverte", HypothesisStatus.DRAFT.value)
        self.status_field.addItem("En cours", HypothesisStatus.IN_PROGRESS.value)
        self.status_field.addItem("Validée", HypothesisStatus.CONCLUDED.value)
        self.status_field.addItem("Rejetée", HypothesisStatus.ARCHIVED.value)
        self._rows = (
            ("Nom", self.name_field),
            ("Nom d'origine", self.original_name_field),
            ("Description", self.description_field),
            ("Type", self.type_field),
            ("Titre", self.content_field),
            ("Confiance", self.confidence_field),
            ("Statut", self.status_field),
        )
        for label, field in self._rows:
            self._form.addRow(label, field)
        self.save_button = QPushButton("Enregistrer", self)
        self.delete_button = QPushButton("Supprimer", self)
        self.show_in_files_button = QPushButton("Afficher dans Fichiers", self)
        self.show_in_files_button.setVisible(False)
        self.evidence_note_group = QGroupBox("Note", self)
        self._evidence_note_layout = QVBoxLayout(self.evidence_note_group)
        self.evidence_note_field = QTextEdit(self.evidence_note_group)
        self._evidence_note_layout.addWidget(self.evidence_note_field)
        self.evidence_hypothesis_group = QGroupBox("Hypothèse", self)
        self._evidence_hypothesis_layout = QVBoxLayout(self.evidence_hypothesis_group)
        self.evidence_hypothesis_field = QLineEdit(self.evidence_hypothesis_group)
        self._evidence_hypothesis_layout.addWidget(self.evidence_hypothesis_field)
        self.relations_group = QGroupBox("Relations", self)
        self._relations_layout = QVBoxLayout(self.relations_group)
        self.create_relation_button = QPushButton("Créer une relation depuis cet objet", self.relations_group)
        self._outgoing_label = QLabel("→ Relations sortantes", self.relations_group)
        self._incoming_label = QLabel("← Relations entrantes", self.relations_group)
        self._relations_layout.addWidget(self.create_relation_button)
        self._relations_layout.addWidget(self._outgoing_label)
        self._relations_layout.addWidget(self._incoming_label)
        self.members_group = QGroupBox("Contenu", self)
        self._members_layout = QVBoxLayout(self.members_group)
        self.attachment_group = QGroupBox("Attachée à", self)
        self._attachment_layout = QVBoxLayout(self.attachment_group)
        self.hypothesis_evidence_group = QGroupBox("Éléments soutenant cette hypothèse", self)
        self._hypothesis_evidence_layout = QVBoxLayout(self.hypothesis_evidence_group)
        self.hypothesis_statistics = QLabel("", self.hypothesis_evidence_group)
        self._hypothesis_evidence_layout.addWidget(self.hypothesis_statistics)
        self.journal_group = QGroupBox("Journal associé", self)
        self._journal_layout = QVBoxLayout(self.journal_group)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.show_in_files_button)
        buttons.addWidget(self.delete_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.breadcrumb_label)
        layout.addWidget(self.return_to_container_button)
        layout.addLayout(self._form)
        layout.addWidget(self.evidence_note_group)
        layout.addWidget(self.evidence_hypothesis_group)
        layout.addWidget(self.attachment_group)
        layout.addWidget(self.hypothesis_evidence_group)
        layout.addWidget(self.journal_group)
        layout.addWidget(self.members_group)
        layout.addWidget(self.relations_group)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self._save)
        self.show_in_files_button.clicked.connect(self._show_in_files)
        self.return_to_container_button.clicked.connect(self._return_to_container)
        self.create_relation_button.clicked.connect(self._create_relation_from_current)
        self.delete_button.clicked.connect(self._delete)

    def set_object(self, kind: str, object_id: str, value, context: SelectionContext | None = None) -> None:
        self._kind = kind
        self._object_id = object_id
        self._navigation_hint = dict(context.navigation_hint) if context is not None else {}
        self._file_target_id = value.subject_id if kind == "item" and value.subject_kind == "file" else None
        self.show_in_files_button.setVisible(self._file_target_id is not None)
        self._set_rows_for(kind)
        if kind == "item":
            self.name_field.setText(value.title or "")
            self.original_name_field.setText("")
            self.description_field.setPlainText(value.summary or "")
            self.type_field.setText(value.subject_kind)
        elif kind == "note":
            title, body = InvestigationTargetRenderer.split_note(value.body)
            self.content_field.setPlainText(body)
            self.description_field.setPlainText(title)
        elif kind == "hypothesis":
            self.name_field.setText(value.title)
            self.description_field.setPlainText(value.description or "")
            self._set_combo_value(self.confidence_field, value.confidence.value)
            self._set_combo_value(self.status_field, value.status.value)
        else:
            self.name_field.setText(value.title)
            self.description_field.setPlainText(value.description or "")
        self._refresh_members()
        self._refresh_relations()
        self._refresh_context_sections(value)
        self._refresh_evidence_context(value)
        self._refresh_navigation(value)

    def set_file_presentation_name(self, name: str) -> None:
        """Reçoit le nom affichable du provider Fichiers, jamais un file_id."""
        if self._kind == "item" and self._file_target_id is not None:
            self.original_name_field.setText(name)

    def _show_in_files(self) -> None:
        if self._file_target_id is not None:
            self.related_selected.emit(
                SelectionContext(
                    "file", self._file_target_id, "investigation_evidence", navigation_hint={"view": "files"}
                )
            )

    def _refresh_navigation(self, value) -> None:
        container_kind = self._navigation_hint.get("container_kind")
        container_id = self._navigation_hint.get("container_id")
        segments: list[tuple[str, SelectionContext]] = []
        if container_kind and container_id:
            segments.append(
                (
                    self._navigation_hint.get("container_title") or self._container_label(container_kind),
                    SelectionContext(container_kind, container_id, "investigation_breadcrumb"),
                )
            )
        if self._kind is not None and self._object_id is not None:
            segments.append(
                (
                    self.name_field.text() or self._targets.label(InvestigationTargetRef(self._kind, self._object_id)),
                    SelectionContext(self._kind, self._object_id, "investigation_breadcrumb"),
                )
            )
        self._set_breadcrumb(segments)
        if container_kind and container_id:
            self.return_to_container_button.setText(f"Retour à la {self._container_label(container_kind)}")
            self.return_to_container_button.setVisible(True)
        else:
            self.return_to_container_button.setVisible(False)

    def _set_breadcrumb(self, segments: list[tuple[str, SelectionContext]]) -> None:
        self._breadcrumb_targets = {str(index): context for index, (_label, context) in enumerate(segments)}
        self.breadcrumb_label.setText(
            " &gt; ".join(f'<a href="{index}">{escape(label)}</a>' for index, (label, _context) in enumerate(segments))
        )
        self.breadcrumb_label.setVisible(bool(segments))

    def _navigate_breadcrumb(self, key: str) -> None:
        context = getattr(self, "_breadcrumb_targets", {}).get(key)
        if context is not None:
            self.related_selected.emit(context)

    def _return_to_container(self) -> None:
        container_kind = self._navigation_hint.get("container_kind")
        container_id = self._navigation_hint.get("container_id")
        if container_kind and container_id:
            self.related_selected.emit(SelectionContext(container_kind, container_id, "investigation_breadcrumb"))

    @staticmethod
    def _container_label(kind: str) -> str:
        return "Case" if kind == "case" else "Collection"

    def _context_for_target(self, target: InvestigationTargetRef, origin: str) -> SelectionContext:
        return InvestigationDetailsNavigation.target_context(
            target,
            origin,
            self._navigation_hint,
            self._kind,
            self._object_id,
            self.name_field.text(),
        )

    def _set_rows_for(self, kind: str) -> None:
        visible_fields = {
            "item": {self.name_field, self.original_name_field},
            "note": {self.description_field, self.content_field},
            "hypothesis": {self.name_field, self.description_field, self.confidence_field, self.status_field},
            "case": {self.name_field, self.description_field},
            "collection": {self.name_field, self.description_field},
        }[kind]
        for _label, field in self._rows:
            field.setVisible(field in visible_fields)
            label = self._form.labelForField(field)
            if label is not None:
                label.setVisible(field in visible_fields)
        if kind == "note":
            label = self._form.labelForField(self.description_field)
            if label is not None:
                label.setText("Titre")
            label = self._form.labelForField(self.content_field)
            if label is not None:
                label.setText("Contenu")
        else:
            label = self._form.labelForField(self.description_field)
            if label is not None:
                label.setText("Description")

    @staticmethod
    def _clear_layout(layout: QVBoxLayout, retained: int = 0) -> None:
        while layout.count() > retained:
            item = layout.takeAt(retained)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _refresh_context_sections(self, value) -> None:
        self.attachment_group.setVisible(self._kind == "note")
        self.hypothesis_evidence_group.setVisible(self._kind == "hypothesis")
        self.journal_group.setVisible(self._kind == "hypothesis")
        if self._kind == "note":
            self._refresh_note_attachment(value)
        elif self._kind == "hypothesis":
            self._refresh_hypothesis_context(value)

    def _refresh_evidence_context(self, value) -> None:
        """Expose les annotations Evidence avant les données de la cible associée."""
        is_item = self._kind == "item"
        self.evidence_note_group.setVisible(False)
        self.evidence_hypothesis_group.setVisible(False)
        if not is_item:
            return
        self.evidence_note_group.setVisible(True)
        self.evidence_hypothesis_group.setVisible(True)
        item_ref = InvestigationTargetRef("item", str(value.item_id))
        context = self._queries.get_target_context(item_ref)
        if context.notes:
            note = context.notes[0]
            self.evidence_note_field.setPlainText(note.body)
        else:
            self.evidence_note_field.clear()
        if context.hypotheses:
            hypothesis = context.hypotheses[0]
            self.evidence_hypothesis_field.setText(hypothesis.title)
        else:
            self.evidence_hypothesis_field.clear()

    def _refresh_note_attachment(self, note) -> None:
        self._clear_layout(self._attachment_layout)
        if note.target_ref is None:
            self._attachment_layout.addWidget(QLabel("Aucune référence associée.", self.attachment_group))
            return
        self._attachment_layout.addWidget(self._target_navigation_button(note.target_ref, self.attachment_group))

    def _refresh_hypothesis_context(self, hypothesis) -> None:
        self._clear_layout(self._hypothesis_evidence_layout, retained=1)
        self._clear_layout(self._journal_layout)
        context = self._queries.get_hypothesis_context(InvestigationHypothesisId(str(hypothesis.hypothesis_id)))
        target = InvestigationTargetRef("hypothesis", str(hypothesis.hypothesis_id))
        direct_context = self._queries.get_target_context(target)
        note_ids = {str(note.note_id) for note in direct_context.notes}
        note_ids.update(
            membership.target_ref.target_id
            for membership in context.memberships
            if membership.target_ref.target_kind == "note"
        )
        self.hypothesis_statistics.setText(
            f"Nombre de preuves : {len(context.memberships)}   •   "
            f"Nombre de notes : {len(note_ids)}   •   "
            f"Nombre de relations : {len(context.relations)}"
        )
        if not context.memberships and not context.relations:
            self._hypothesis_evidence_layout.addWidget(QLabel("Aucun élément associé.", self.hypothesis_evidence_group))
        for membership in context.memberships:
            label = f"{membership.role.value}: {self._targets.label(membership.target_ref)}"
            self._hypothesis_evidence_layout.addWidget(
                self._target_navigation_button(membership.target_ref, self.hypothesis_evidence_group, label)
            )
        for relation in context.relations:
            related_target = relation.destination_target if relation.source_target == target else relation.source_target
            label = f"Relation {relation.relation_type.value}: {self._targets.label(related_target)}"
            self._hypothesis_evidence_layout.addWidget(
                self._target_navigation_button(related_target, self.hypothesis_evidence_group, label)
            )
        journal_entries = self._queries.get_journal_for_target(target)
        if not journal_entries:
            self._journal_layout.addWidget(QLabel("Aucune entrée de journal.", self.journal_group))
        for entry in journal_entries:
            label = InvestigationJournalRenderer.label(entry)
            if entry.target_ref is None:
                self._journal_layout.addWidget(QLabel(label, self.journal_group))
            else:
                self._journal_layout.addWidget(
                    self._target_navigation_button(entry.target_ref, self.journal_group, label)
                )

    def _target_navigation_button(
        self, target: InvestigationTargetRef, parent: QWidget, label: str | None = None
    ) -> QPushButton:
        button = QPushButton(label or self._targets.label(target), parent)
        button.clicked.connect(
            lambda _checked=False, reference=target: self.related_selected.emit(
                self._context_for_target(reference, "investigation_context")
            )
        )
        return button

    def _refresh_members(self) -> None:
        """Affiche seulement les références des contenus, résolues via le service public."""
        while self._members_layout.count():
            item = self._members_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if self._kind not in {"case", "collection"} or self._object_id is None:
            self.members_group.setVisible(False)
            return
        self.members_group.setVisible(True)
        if self._kind == "case":
            context = self._queries.get_case_context(InvestigationCaseId(self._object_id))
            targets = context.members
            post_its = context.notes
            container_label = "Case"
        else:
            context = self._queries.get_collection_context(InvestigationCollectionId(self._object_id))
            targets = context.members
            post_its = context.notes
            container_label = "Collection"
        visible_targets = tuple(target for target in targets if target.target_kind in {"item", "collection"})
        if not visible_targets and not post_its:
            self._members_layout.addWidget(
                QLabel(f"Contenu de la {container_label.lower()} — aucun élément.", self.members_group)
            )
            return
        for target in visible_targets:
            self._members_layout.addWidget(self._member_row(target, container_label))
        for post_it in post_its:
            self._members_layout.addWidget(QLabel(f"📝 Post-it — {post_it.body}", self.members_group))

    def _create_post_it(self) -> None:
        if self._kind not in {"case", "collection"} or self._object_id is None:
            return
        dialog = NoteCreationDialog(self)
        dialog.setWindowTitle("Ajouter un post-it")
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        target = InvestigationTargetRef(self._kind, self._object_id)
        body = dialog.body_field.toPlainText().strip()
        if dialog.title_field.text().strip():
            body = f"{dialog.title_field.text().strip()}\n\n{body}"
        try:
            self._service.create_note(body, target_ref=target)
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._refresh_members()

    def _member_row(self, target: InvestigationTargetRef, container_label: str) -> QWidget:
        row = QWidget(self.members_group)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        navigate = _MemberNavigationButton(self._targets.with_icon(target), row)
        navigate.setToolTip("Double-cliquez pour ouvrir l'objet.")
        navigate.double_clicked.connect(
            lambda: self.related_selected.emit(self._context_for_target(target, "investigation_membership"))
        )
        navigate.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        navigate.customContextMenuRequested.connect(
            lambda position, button=navigate, member=target, label=container_label: self._show_member_menu(
                button, position, member, label
            )
        )
        remove = QPushButton("Retirer", row)
        remove.clicked.connect(lambda _checked=False, member=target: self._remove_member(member))
        layout.addWidget(navigate, 1)
        layout.addWidget(remove)
        return row

    @staticmethod
    def _member_icon(kind: str) -> str:
        return {
            "item": "\U0001f4c4",
            "note": "\U0001f4dd",
            "hypothesis": "\U0001f4a1",
            "collection": "\U0001f4c2",
        }.get(kind, "\U0001f4c4")

    def _show_member_menu(
        self, button: QPushButton, position, target: InvestigationTargetRef, container_label: str
    ) -> None:
        self._member_menu(button, target, container_label).exec(button.mapToGlobal(position))

    def _member_menu(self, button: QPushButton, target: InvestigationTargetRef, container_label: str):
        """Construit le menu de retrait sans donner de responsabilité métier au widget."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(button)
        action = menu.addAction(f"Retirer de cette {container_label}")
        action.triggered.connect(lambda: self._remove_member(target))
        return menu

    def _remove_member(self, target: InvestigationTargetRef) -> None:
        InvestigationMembershipActions.remove(self._service, self._kind, self._object_id, target)
        self._refresh_members()

    def _save(self) -> None:
        if self._kind is None or self._object_id is None:
            return
        try:
            self._save_current()
        except ValueError as error:
            QMessageBox.warning(self, "Modification impossible", str(error))

    def _save_current(self) -> None:
        assert self._kind is not None and self._object_id is not None
        self._editor.save(
            self._kind,
            self._object_id,
            name=self.name_field.text().strip(),
            description=self.description_field.toPlainText().strip(),
            subject_kind=self.type_field.text().strip(),
            content=self.content_field.toPlainText().strip(),
            confidence=str(self.confidence_field.currentData()),
            status=str(self.status_field.currentData()),
            evidence_note=self.evidence_note_field.toPlainText().strip(),
            evidence_hypothesis=self.evidence_hypothesis_field.text().strip(),
        )

    def _delete(self) -> None:
        if self._kind is None or self._object_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Supprimer",
            "Voulez-vous vraiment supprimer cet objet ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self._kind == "item":
                self._service.delete_item(InvestigationItemId(self._object_id))
            elif self._kind == "note":
                self._service.delete_note(InvestigationNoteId(self._object_id))
            elif self._kind == "hypothesis":
                self._service.delete_hypothesis(InvestigationHypothesisId(self._object_id))
            elif self._kind == "case":
                self._service.delete_case(InvestigationCaseId(self._object_id))
            elif self._kind == "collection":
                self._service.delete_collection(InvestigationCollectionId(self._object_id))
        except ValueError as error:
            QMessageBox.warning(self, "Suppression impossible", str(error))
            return
        self.deleted.emit()

    def _refresh_relations(self) -> None:
        while self._relations_layout.count() > 3:
            item = self._relations_layout.takeAt(3)
            if item.widget() is not None:
                item.widget().deleteLater()
        if self._kind is None or self._object_id is None:
            return
        target = InvestigationTargetRef(self._kind, self._object_id)
        outgoing = []
        incoming = []
        for relation in self._service.find_relations_for_target(target):
            if relation.source_target == target:
                outgoing.append((relation, relation.destination_target, "→"))
            if relation.destination_target == target:
                incoming.append((relation, relation.source_target, "←"))
        self._outgoing_label.setText("→ Relations sortantes" if outgoing else "→ Relations sortantes — aucune")
        self._incoming_label.setText("← Relations entrantes" if incoming else "← Relations entrantes — aucune")
        for relation, related_target, direction in (*outgoing, *incoming):
            self._relations_layout.addWidget(self._relation_row(relation, related_target, direction))

    def _relation_row(self, relation, related_target: InvestigationTargetRef, direction: str) -> QWidget:
        row = QWidget(self.relations_group)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        source = self._target_navigation_button(
            relation.source_target, row, self._targets.with_icon(relation.source_target)
        )
        verb = QLabel(f"↓\n{InvestigationRelationRenderer.phrase(relation.relation_type)}\n↓", row)
        verb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        destination = self._target_navigation_button(
            relation.destination_target,
            row,
            self._targets.with_icon(relation.destination_target),
        )
        remove = QPushButton("Supprimer", row)
        remove.clicked.connect(
            lambda _checked=False, relation_id=relation.relation_id: self._delete_relation(relation_id)
        )
        layout.addWidget(source)
        layout.addWidget(verb)
        layout.addWidget(destination)
        layout.addWidget(remove)
        return row

    def _create_relation_from_current(self) -> None:
        if self._kind is None or self._object_id is None:
            return
        source = InvestigationTargetRef(self._kind, self._object_id)
        targets = self._relation_targets()
        dialog = RelationCreationDialog(targets, self._relation_types(), self)
        source_index = next(
            (
                row
                for row in range(dialog.source_field.count())
                if tuple(dialog.source_field.itemData(row)) == (source.target_kind, source.target_id)
            ),
            -1,
        )
        if source_index < 0:
            QMessageBox.warning(
                self, "Création impossible", "L'objet affiché ne peut pas être la source de cette relation."
            )
            return
        dialog.source_field.setCurrentIndex(source_index)
        dialog.source_field.setEnabled(False)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self._service.create_relation(
                source,
                InvestigationTargetRef(*tuple(dialog.destination_field.currentData())),
                InvestigationRelationType(str(dialog.relation_type_field.currentData())),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._refresh_relations()

    def _relation_targets(self) -> tuple[tuple[str, str, str], ...]:
        targets = []
        targets.extend(
            (self._targets.with_icon(InvestigationTargetRef("item", str(item.item_id))), "item", str(item.item_id))
            for item in self._service.list_items()
        )
        targets.extend(
            (self._targets.with_icon(InvestigationTargetRef("note", str(note.note_id))), "note", str(note.note_id))
            for note in self._service.list_notes()
        )
        targets.extend(
            (
                self._targets.with_icon(InvestigationTargetRef("hypothesis", str(item.hypothesis_id))),
                "hypothesis",
                str(item.hypothesis_id),
            )
            for item in self._service.list_hypotheses()
        )
        targets.extend(
            (self._targets.with_icon(InvestigationTargetRef("case", str(item.case_id))), "case", str(item.case_id))
            for item in self._service.list_cases()
        )
        targets.extend(
            (
                self._targets.with_icon(InvestigationTargetRef("collection", str(item.collection_id))),
                "collection",
                str(item.collection_id),
            )
            for item in self._service.list_collections()
        )
        return tuple(targets)

    @staticmethod
    def _relation_types() -> tuple[tuple[str, str], ...]:
        return tuple((InvestigationRelationRenderer.phrase(value), value.value) for value in InvestigationRelationType)

    def _delete_relation(self, relation_id: InvestigationRelationId) -> None:
        try:
            self._service.delete_relation(relation_id)
        except ValueError as error:
            QMessageBox.warning(self, "Suppression impossible", str(error))
            return
        self._refresh_relations()

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)


class InvestigationDetailsProvider:
    """Point d'extension du panneau partagé, branché uniquement sur le service public."""

    _SUPPORTED_KINDS = frozenset({"item", "note", "hypothesis", "case", "collection"})

    def __init__(
        self,
        service: InvestigationService,
        queries: InvestigationQueryService | None = None,
        entity_resolver: CanonicalEntityResolver | None = None,
    ) -> None:
        self._service = service
        self._queries = queries or InvestigationQueryService(service)
        self._entity_resolver = entity_resolver or CanonicalEntityResolver()
        self._preview = InvestigationPreviewBridge(self._entity_resolver)
        self._widget: InvestigationDetailsWidget | None = None

    def supports(self, context: SelectionContext) -> bool:
        return context.subject_kind in self._SUPPORTED_KINDS

    def populate(self, panel: DetailsPanelHost, context: SelectionContext) -> None:
        value = self._value_for(context)
        if value is None:
            panel.clear_provider_widget()
            return
        if self._widget is None:
            self._widget = InvestigationDetailsWidget(self._service, self._queries, panel.widget())
            self._widget.deleted.connect(panel.clear_provider_widget)
            self._widget.related_selected.connect(panel.publish_context)
        self._widget.set_object(context.subject_kind, context.subject_id, value, context)
        if self._preview.present(panel, value, context, self._widget):
            return
        panel.show_provider_widget(self._title_for(context.subject_kind), self._widget)

    def _value_for(self, context: SelectionContext):
        if context.subject_kind == "item":
            return self._service.get_item(InvestigationItemId(context.subject_id))
        if context.subject_kind == "note":
            return self._service.get_note(InvestigationNoteId(context.subject_id))
        if context.subject_kind == "hypothesis":
            return self._service.get_hypothesis(InvestigationHypothesisId(context.subject_id))
        if context.subject_kind == "case":
            return self._service.get_case(InvestigationCaseId(context.subject_id))
        return self._service.get_collection(InvestigationCollectionId(context.subject_id))

    @staticmethod
    def _title_for(kind: str) -> str:
        return {
            "item": "Élément Investigation",
            "note": "Note Investigation",
            "hypothesis": "Hypothèse Investigation",
            "case": "Case Investigation",
            "collection": "Collection Investigation",
        }[kind]
