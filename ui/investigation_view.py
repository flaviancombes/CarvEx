"""Vue MVC minimale du module Investigation, strictement en lecture."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from PySide6.QtCore import QModelIndex, QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.events import EventType, InvestigationEvent
from investigation.hypothesis import HypothesisRole, InvestigationHypothesisId
from investigation.integrity import IntegrityReport, InvestigationIntegrityValidator
from investigation.item import InvestigationItemId
from investigation.journal import InvestigationJournalEntry
from investigation.note import InvestigationNoteId
from investigation.queries import InvestigationQueryService
from investigation.relation import InvestigationRelationType
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from models.investigation_tree_model import InvestigationSection, InvestigationTreeEntry, InvestigationTreeModel
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.context import SelectionContext
from selection.manager import SelectionManager
from ui.investigation_commands import InvestigationCommandGateway
from ui.investigation_dialogs import (
    CaseCreationDialog,
    CollectionCreationDialog,
    EvidenceDialog,
    HypothesisCreationDialog,
    ItemCreationDialog,
    MembershipSelectionDialog,
    NoteCreationDialog,
    RelationCreationDialog,
)
from ui.investigation_drag_drop import InvestigationDragDropPolicy
from ui.investigation_evidence import InvestigationEvidenceWorkflow
from ui.investigation_journal_formatter import InvestigationJournalFormatter


@dataclass(frozen=True, slots=True)
class EvidenceFormContext:
    """Projection UI d'une preuve, sans copie ni dépendance de persistance."""

    existing: bool
    display_name: str
    note: str
    hypothesis: str
    selected_case_id: str | None
    selected_collection_id: str | None
    cases: tuple[tuple[str, str], ...]
    collections: tuple[tuple[str, str], ...]


class InvestigationTreeView(QTreeView):
    """Vue Qt sans accès au domaine ; elle ne signale que les intentions utilisateur."""

    section_expanded = Signal(object)
    entry_selected = Signal(object)
    membership_requested = Signal(object, object)
    context_menu_requested = Signal(object, object)
    entry_activated = Signal(object)

    def __init__(self, model: InvestigationTreeModel, parent=None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setHeaderHidden(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.expanded.connect(self._on_expanded)
        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.doubleClicked.connect(self._on_activated)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _on_expanded(self, index: QModelIndex) -> None:
        model = self.model()
        if isinstance(model, InvestigationTreeModel):
            section = model.section_for_index(index)
            if section is not None:
                self.section_expanded.emit(section)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        model = self.model()
        if isinstance(model, InvestigationTreeModel):
            entry = model.entry_for_index(current)
            if entry is not None:
                self.entry_selected.emit(entry)

    def _on_activated(self, index: QModelIndex) -> None:
        entry = self._entry_at(index)
        if entry is not None:
            self.entry_activated.emit(entry)

    def dropEvent(self, event) -> None:  # noqa: N802
        source = self._entry_at(self.currentIndex())
        target = self._entry_at(self.indexAt(event.position().toPoint()))
        if self.request_membership(source, target):
            event.acceptProposedAction()
            return
        event.ignore()

    def request_membership(self, source: InvestigationTreeEntry | None, target: InvestigationTreeEntry | None) -> bool:
        if not InvestigationDragDropPolicy.accepts(source, target):
            return False
        """Point testable du DnD : la vue n'exécute aucune commande métier."""
        if source is None or target is None:
            return False
        if source.subject_kind not in {"item", "collection"}:
            return False
        if target.subject_kind not in {"case", "collection"}:
            return False
        if source.subject_kind == "collection" and target.subject_kind != "case":
            return False
        self.membership_requested.emit(source, target)
        return True

    def _on_context_menu(self, position: QPoint) -> None:
        entry = self._entry_at(self.indexAt(position))
        if entry is not None:
            self.context_menu_requested.emit(entry, self.viewport().mapToGlobal(position))

    def _entry_at(self, index: QModelIndex) -> InvestigationTreeEntry | None:
        model = self.model()
        return model.entry_for_index(index) if isinstance(model, InvestigationTreeModel) else None


class InvestigationController(QObject):
    """Orchestre les lectures, l'EventBus et la sélection sans logique de vue métier."""

    selection_requested = Signal(object)
    integrity_changed = Signal(object)
    item_presence_changed = Signal(bool)
    file_item_changed = Signal(str)

    _SECTIONS_BY_EVENT = {
        EventType.ITEM_CREATED: InvestigationSection.ITEMS,
        EventType.ITEM_UPDATED: InvestigationSection.ITEMS,
        EventType.ITEM_DELETED: InvestigationSection.ITEMS,
        EventType.CASE_CREATED: InvestigationSection.CASES,
        EventType.CASE_UPDATED: InvestigationSection.CASES,
        EventType.CASE_DELETED: InvestigationSection.CASES,
        EventType.COLLECTION_CREATED: InvestigationSection.COLLECTIONS,
        EventType.COLLECTION_UPDATED: InvestigationSection.COLLECTIONS,
        EventType.COLLECTION_DELETED: InvestigationSection.COLLECTIONS,
        EventType.HYPOTHESIS_CREATED: InvestigationSection.ITEMS,
        EventType.HYPOTHESIS_UPDATED: InvestigationSection.ITEMS,
        EventType.HYPOTHESIS_DELETED: InvestigationSection.ITEMS,
        EventType.NOTE_CREATED: InvestigationSection.POST_ITS,
        EventType.NOTE_UPDATED: InvestigationSection.POST_ITS,
        EventType.NOTE_DELETED: InvestigationSection.POST_ITS,
    }

    def __init__(
        self,
        service: InvestigationService,
        queries: InvestigationQueryService,
        validator: InvestigationIntegrityValidator,
        model: InvestigationTreeModel,
        entity_resolver: CanonicalEntityResolver | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._queries = queries
        self._validator = validator
        self._model = model
        self._entity_resolver = entity_resolver
        self._commands = InvestigationCommandGateway(service, entity_resolver)
        self._evidence = InvestigationEvidenceWorkflow(service, queries, self._commands, entity_resolver)
        self._journal_formatter = InvestigationJournalFormatter(service)
        self._bus = service.event_bus
        self._event_subscriber = self._on_domain_event
        if self._bus is not None:
            self._bus.subscribe(self._event_subscriber)

    @property
    def service(self) -> InvestigationService:
        """Façade publique des commandes ; aucun repository n'est exposé à l'UI."""
        return self._service

    def close(self) -> None:
        if self._bus is not None:
            self._bus.unsubscribe(self._event_subscriber)
        self._bus = None

    def validate(self) -> IntegrityReport:
        report = self._validator.validate()
        self.integrity_changed.emit(report)
        return report

    def load_section(self, section: InvestigationSection) -> None:
        if not self._model.is_loaded(section):
            self.refresh_section(section)

    def refresh_section(self, section: InvestigationSection) -> None:
        self._model.set_entries(section, self._entries_for(section))

    def create_item(self, title: str, description: str, subject_kind: str):
        return self._commands.create_item(title, description, subject_kind)

    def create_note(self, title: str, body: str, target_ref: InvestigationTargetRef | None = None):
        return self._commands.create_note(title, body, target_ref)

    def create_hypothesis(
        self,
        title: str,
        description: str,
        confidence: str,
        status: str,
        target_ref: InvestigationTargetRef | None = None,
    ):
        return self._commands.create_hypothesis(title, description, confidence, status, target_ref)

    def add_file_item(self, file_id: str, title: str):
        """Crée au plus un Item pour le file_id stable du rapport importé."""
        return self._commands.add_file_item(file_id, title)

    def add_target_item(self, target: InvestigationTargetRef, title: str):
        """Commande générique pour toute preuve référencée par une vue CarvEx."""
        return self._commands.add_target_item(target, title)

    def evidence_form_context(self, target: InvestigationTargetRef, fallback_name: str) -> EvidenceFormContext:
        """Prépare le formulaire depuis les projections publiques, sans repository."""
        target = self._canonical_evidence_target(target)
        source_context = self._queries.get_target_context(target)
        item = source_context.item
        if item is None:
            return EvidenceFormContext(
                False,
                fallback_name,
                "",
                "",
                None,
                None,
                self.containers("case"),
                self.containers("collection"),
            )
        item_ref = InvestigationTargetRef("item", str(item.item_id))
        item_context = self._queries.get_target_context(item_ref)
        notes = item_context.notes or source_context.notes
        hypotheses = item_context.hypotheses or source_context.hypotheses
        cases = item_context.cases or source_context.cases
        collections = item_context.collections or source_context.collections
        return EvidenceFormContext(
            True,
            item.title or fallback_name,
            notes[0].body if notes else "",
            hypotheses[0].title if hypotheses else "",
            str(cases[0].case_id) if cases else None,
            str(collections[0].collection_id) if collections else None,
            self.containers("case"),
            self.containers("collection"),
        )

    def evidence_context(self, target: InvestigationTargetRef, fallback_name: str):
        """Façade Evidence dédiée utilisée par les widgets Qt."""
        return self._evidence.form_context(target, fallback_name)

    def apply_evidence(
        self,
        target: InvestigationTargetRef,
        *,
        display_name: str,
        note: str,
        hypothesis: str,
        case_id: str | None,
        collection_id: str | None,
    ):
        """Exécute le workflow Evidence extrait sans exposer son implémentation."""
        return self._evidence.save(
            target,
            display_name=display_name,
            note=note,
            hypothesis=hypothesis,
            case_id=case_id,
            collection_id=collection_id,
        )

    def save_evidence(
        self,
        target: InvestigationTargetRef,
        *,
        display_name: str,
        note: str,
        hypothesis: str,
        case_id: str | None,
        collection_id: str | None,
    ):
        """Exécute les commandes de preuve via InvestigationService et son EventBus."""
        target = self._canonical_evidence_target(target)
        source_context = self._queries.get_target_context(target)
        item = source_context.item
        now = datetime.now(UTC)
        if item is None:
            item = self._service.create_item(target.target_kind, target.target_id, title=display_name)
        elif item.title != display_name:
            item = self._service.update_item(replace(item, title=display_name, updated_at=now))

        item_ref = InvestigationTargetRef("item", str(item.item_id))
        item_context = self._queries.get_target_context(item_ref)
        self._save_evidence_note(item_context.notes or source_context.notes, item_ref, note, now)
        self._save_evidence_hypothesis(item_context.hypotheses or source_context.hypotheses, item_ref, hypothesis, now)
        self._synchronise_evidence_container(item_context.cases, item_ref, case_id, "case")
        self._synchronise_evidence_container(item_context.collections, item_ref, collection_id, "collection")
        return item

    def _canonical_evidence_target(self, target: InvestigationTargetRef) -> InvestigationTargetRef:
        """Réduit les représentations UI d'un fichier à ``file/file_id``."""
        resolved = self._entity_resolver.resolve(target) if self._entity_resolver is not None else None
        if resolved is not None and resolved.is_file:
            return InvestigationTargetRef("file", resolved.identifier)
        return target

    def _save_evidence_note(self, notes, item_ref: InvestigationTargetRef, body: str, now: datetime) -> None:
        content = body.strip()
        if not content:
            return
        if notes:
            note = notes[0]
            if note.body != content or note.target_ref != item_ref:
                self._service.update_note(replace(note, body=content, target_ref=item_ref, updated_at=now))
            return
        self._service.create_note(content, target_ref=item_ref)

    def _save_evidence_hypothesis(
        self, hypotheses, item_ref: InvestigationTargetRef, title: str, now: datetime
    ) -> None:
        value = title.strip()
        if not value:
            return
        hypothesis = hypotheses[0] if hypotheses else self._service.create_hypothesis(value)
        if hypothesis.title != value:
            hypothesis = self._service.update_hypothesis(replace(hypothesis, title=value, updated_at=now))
        memberships = self._queries.get_hypothesis_context(hypothesis.hypothesis_id).memberships
        if all(membership.target_ref != item_ref for membership in memberships):
            self._service.add_to_hypothesis(hypothesis.hypothesis_id, item_ref, HypothesisRole.OBSERVATION)

    def _synchronise_evidence_container(
        self, containers, item_ref: InvestigationTargetRef, selected_id: str | None, kind: str
    ) -> None:
        identifier_attr = "case_id" if kind == "case" else "collection_id"
        for container in containers:
            identifier = str(getattr(container, identifier_attr))
            if identifier != selected_id:
                if kind == "case":
                    self._service.remove_from_case(InvestigationCaseId(identifier), item_ref)
                else:
                    self._service.remove_from_collection(InvestigationCollectionId(identifier), item_ref)
        if selected_id and all(str(getattr(container, identifier_attr)) != selected_id for container in containers):
            if kind == "case":
                self._service.add_to_case(InvestigationCaseId(selected_id), item_ref)
            else:
                self._service.add_to_collection(InvestigationCollectionId(selected_id), item_ref)

    def has_file_item(self, file_id: str) -> bool:
        return self._commands.has_file_item(file_id)

    def has_target_item(self, target: InvestigationTargetRef) -> bool:
        return self._commands.has_target_item(target)

    def create_case(self, title: str, description: str):
        return self._commands.create_case(title, description)

    def create_collection(self, title: str, description: str):
        return self._commands.create_collection(title, description)

    def relation_options(self) -> tuple[tuple[tuple[str, str, str], ...], tuple[tuple[str, str], ...]]:
        """Expose le catalogue Relations extrait pour les dialogues Qt."""
        return self._commands.relation_targets(), self._commands.relation_types()

    def create_relation_command(self, source: tuple[str, str], relation_type: str, destination: tuple[str, str]):
        return self._commands.create_relation(source, relation_type, destination)

    def container_options(self, kind: str) -> tuple[tuple[str, str], ...]:
        return self._commands.containers(kind)

    def organize_entry(self, entry: InvestigationTreeEntry, container_kind: str, container_id: str) -> None:
        self._commands.add_to_container(entry, container_kind, container_id)

    def relation_targets(self) -> tuple[tuple[str, str, str], ...]:
        """Expose des références légères à l'UI, jamais les index du repository."""
        targets = []
        targets.extend(
            (f"Élément — {item.title or item.subject_kind}", "item", str(item.item_id))
            for item in self._service.list_items()
        )
        targets.extend(
            (f"Note — {self._summary(note.body)}", "note", str(note.note_id)) for note in self._service.list_notes()
        )
        targets.extend(
            (f"Hypothèse — {item.title}", "hypothesis", str(item.hypothesis_id))
            for item in self._service.list_hypotheses()
        )
        targets.extend((f"Case — {item.title}", "case", str(item.case_id)) for item in self._service.list_cases())
        targets.extend(
            (f"Collection — {item.title}", "collection", str(item.collection_id))
            for item in self._service.list_collections()
        )
        return tuple(targets)

    @staticmethod
    def relation_types() -> tuple[tuple[str, str], ...]:
        return tuple(
            (relation_type.value.replace("_", " ").title(), relation_type.value)
            for relation_type in InvestigationRelationType
        )

    def create_relation(self, source: tuple[str, str], relation_type: str, destination: tuple[str, str]):
        return self._service.create_relation(
            InvestigationTargetRef(*source),
            InvestigationTargetRef(*destination),
            InvestigationRelationType(relation_type),
        )

    def containers(self, kind: str) -> tuple[tuple[str, str], ...]:
        if kind == "case":
            return tuple((case.title, str(case.case_id)) for case in self._service.list_cases())
        if kind == "collection":
            return tuple(
                (collection.title, str(collection.collection_id)) for collection in self._service.list_collections()
            )
        return ()

    def add_to_container(self, entry: InvestigationTreeEntry, container_kind: str, container_id: str) -> None:
        target = InvestigationTargetRef(entry.subject_kind, entry.subject_id)
        if container_kind == "case":
            self._service.add_to_case(InvestigationCaseId(container_id), target)
        elif container_kind == "collection":
            self._service.add_to_collection(InvestigationCollectionId(container_id), target)
        else:
            raise ValueError(f"Type de conteneur non pris en charge : {container_kind}")

    def select_entry(self, entry: InvestigationTreeEntry) -> None:
        """Résout le contexte via QueryService puis publie une référence légère."""
        related_target = entry.related_target_ref
        if entry.subject_kind == "case":
            self._queries.get_case_context(InvestigationCaseId(entry.subject_id))
        elif entry.subject_kind == "collection":
            self._queries.get_collection_context(InvestigationCollectionId(entry.subject_id))
        elif entry.subject_kind == "hypothesis":
            self._queries.get_hypothesis_context(InvestigationHypothesisId(entry.subject_id))
        elif related_target is not None:
            self._queries.get_target_context(related_target)
        else:
            self._queries.get_target_context(InvestigationTargetRef(entry.subject_kind, entry.subject_id))

        resolved = (
            self._entity_resolver.resolve(related_target)
            if related_target is not None and self._entity_resolver is not None
            else None
        )
        related_ids = {"file_id": resolved.identifier} if resolved is not None and resolved.is_file else {}
        self.selection_requested.emit(
            SelectionContext(entry.subject_kind, entry.subject_id, "investigation_view", related_ids=related_ids)
        )

    def _on_domain_event(self, event) -> None:
        if not isinstance(event, InvestigationEvent):
            return
        if event.event_type is EventType.BATCH_COMPLETED:
            if event.parent_kind == "items" and self._model.is_loaded(InvestigationSection.ITEMS):
                self.refresh_section(InvestigationSection.ITEMS)
            elif event.parent_kind == "collection":
                if self._model.is_loaded(InvestigationSection.COLLECTIONS):
                    self.refresh_section(InvestigationSection.COLLECTIONS)
                if self._model.is_loaded(InvestigationSection.ITEMS):
                    self.refresh_section(InvestigationSection.ITEMS)
            if self._model.is_loaded(InvestigationSection.JOURNAL):
                self.refresh_section(InvestigationSection.JOURNAL)
            self.item_presence_changed.emit(self._has_tree_content())
            return
        section = self._SECTIONS_BY_EVENT.get(event.event_type)
        if section is None and event.event_type in {EventType.MEMBERSHIP_ADDED, EventType.MEMBERSHIP_REMOVED}:
            section = {
                "case": InvestigationSection.CASES,
                "collection": InvestigationSection.COLLECTIONS,
                "hypothesis": InvestigationSection.ITEMS,
                "tag": InvestigationSection.ITEMS,
            }.get(event.parent_kind or "")
        if section is not None:
            self.refresh_section(section)
        if self._model.is_loaded(InvestigationSection.JOURNAL):
            self.refresh_section(InvestigationSection.JOURNAL)
        if event.event_type in {
            EventType.ITEM_CREATED,
            EventType.CASE_CREATED,
            EventType.COLLECTION_CREATED,
            EventType.NOTE_CREATED,
            EventType.RELATION_CREATED,
        }:
            self.item_presence_changed.emit(True)
        elif event.event_type in {
            EventType.ITEM_DELETED,
            EventType.CASE_DELETED,
            EventType.COLLECTION_DELETED,
            EventType.NOTE_DELETED,
            EventType.RELATION_DELETED,
        }:
            self.item_presence_changed.emit(self._has_tree_content())
        if event.event_type in {EventType.ITEM_CREATED, EventType.ITEM_DELETED}:
            if event.target_ref is not None and event.target_ref.target_kind == "file":
                self.file_item_changed.emit(event.target_ref.target_id)

    def _has_tree_content(self) -> bool:
        return bool(
            self._service.list_items()
            or self._service.list_cases()
            or self._service.list_collections()
            or self._service.list_notes()
        )

    def _entries_for(self, section: InvestigationSection) -> tuple[InvestigationTreeEntry, ...]:
        if section is InvestigationSection.ITEMS:
            return tuple(
                InvestigationTreeEntry(
                    "item",
                    str(item.item_id),
                    f"📄 {item.title or item.subject_kind}",
                    item.status.value,
                    related_target_ref=InvestigationTargetRef(item.subject_kind, item.subject_id),
                )
                for item in self._service.list_items()
            )
        if section is InvestigationSection.CASES:
            return tuple(
                InvestigationTreeEntry("case", str(item.case_id), f"📁 {item.title}", item.status.value)
                for item in self._service.list_cases()
            )
        if section is InvestigationSection.COLLECTIONS:
            return tuple(
                InvestigationTreeEntry("collection", str(item.collection_id), f"🗂 {item.title}")
                for item in self._service.list_collections()
            )
        if section is InvestigationSection.POST_ITS:
            return tuple(
                InvestigationTreeEntry("note", str(note.note_id), f"📝 {self._summary(note.body)}")
                for note in self._service.list_notes()
                if note.target_ref is None or note.target_ref.target_kind in {"case", "collection"}
            )
        return tuple(self._journal_formatter.entry(item) for item in self._service.list_entries())

    @staticmethod
    def _summary(value: str, limit: int = 90) -> str:
        compact = " ".join(value.split())
        return compact if len(compact) <= limit else f"{compact[: limit - 1]}…"

    def _journal_entry(self, entry: InvestigationJournalEntry) -> InvestigationTreeEntry:
        timestamp = entry.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        action = {
            EventType.ITEM_CREATED: "Nouvelle preuve",
            EventType.ITEM_UPDATED: "Preuve modifiée",
            EventType.NOTE_CREATED: (
                "Post-it ajouté"
                if entry.target_ref is None or entry.target_ref.target_kind in {"case", "collection"}
                else "Note ajoutée"
            ),
            EventType.NOTE_UPDATED: (
                "Post-it modifié"
                if entry.target_ref is None or entry.target_ref.target_kind in {"case", "collection"}
                else "Note modifiée"
            ),
            EventType.HYPOTHESIS_CREATED: "Hypothèse créée",
            EventType.HYPOTHESIS_UPDATED: "Modification d'une hypothèse",
            EventType.RELATION_CREATED: "Création d'une relation",
            EventType.MEMBERSHIP_ADDED: "Organisation mise à jour",
        }.get(entry.event_type, entry.event_type.value.replace("_", " ").capitalize())
        target = entry.target_ref
        label = self._journal_label(entry)
        return InvestigationTreeEntry(
            "journal_entry",
            str(entry.entry_id),
            action,
            f"{timestamp} — {label}",
            related_target_ref=target,
        )

    def _journal_label(self, entry: InvestigationJournalEntry) -> str:
        target_label = (
            self._target_label(entry.target_ref) if entry.target_ref is not None else self._entity_label(entry)
        )
        if entry.event_type is EventType.MEMBERSHIP_ADDED and entry.parent_ref is not None:
            return f"{target_label} ajouté à {self._target_label(entry.parent_ref)}"
        if entry.event_type is EventType.MEMBERSHIP_REMOVED and entry.parent_ref is not None:
            return f"{target_label} retiré de {self._target_label(entry.parent_ref)}"
        if entry.event_type is EventType.RELATION_CREATED:
            related_kind = entry.context.get("related_target_kind")
            related_id = entry.context.get("related_target_id")
            if related_kind and related_id:
                related = InvestigationTargetRef(related_kind, related_id)
                return f"{target_label} lié à {self._target_label(related)}"
        return target_label

    def _entity_label(self, entry: InvestigationJournalEntry) -> str:
        entity_id = entry.context.get("entity_id", "")
        if entry.event_type in {EventType.NOTE_CREATED, EventType.NOTE_UPDATED, EventType.NOTE_DELETED}:
            value = self._service.get_note(InvestigationNoteId(entity_id)) if entity_id else None
            return self._summary(value.body) if value is not None else "Post-it supprimé"
        if entry.event_type in {EventType.CASE_CREATED, EventType.CASE_UPDATED, EventType.CASE_DELETED}:
            value = self._service.get_case(InvestigationCaseId(entity_id)) if entity_id else None
            return value.title if value is not None else "Case supprimée"
        if entry.event_type in {
            EventType.COLLECTION_CREATED,
            EventType.COLLECTION_UPDATED,
            EventType.COLLECTION_DELETED,
        }:
            value = self._service.get_collection(InvestigationCollectionId(entity_id)) if entity_id else None
            return value.title if value is not None else "Collection supprimée"
        if entry.event_type in {
            EventType.HYPOTHESIS_CREATED,
            EventType.HYPOTHESIS_UPDATED,
            EventType.HYPOTHESIS_DELETED,
        }:
            value = self._service.get_hypothesis(InvestigationHypothesisId(entity_id)) if entity_id else None
            return value.title if value is not None else "Hypothèse supprimée"
        return "Objet"

    def _target_label(self, target: InvestigationTargetRef | None) -> str:
        if target is None:
            return "Objet"
        if target.target_kind == "file":
            item = self._service.find_item_by_subject("file", target.target_id)
            return item.title or "Fichier" if item is not None else "Fichier"
        if target.target_kind == "item":
            item = self._service.get_item(InvestigationItemId(target.target_id))
            return item.title or "Preuve" if item is not None else "Preuve supprimée"
        if target.target_kind == "case":
            value = self._service.get_case(InvestigationCaseId(target.target_id))
            return value.title if value is not None else "Case supprimée"
        if target.target_kind == "collection":
            value = self._service.get_collection(InvestigationCollectionId(target.target_id))
            return value.title if value is not None else "Collection supprimée"
        if target.target_kind == "hypothesis":
            value = self._service.get_hypothesis(InvestigationHypothesisId(target.target_id))
            return value.title if value is not None else "Hypothèse supprimée"
        return "Objet supprimé"


class InvestigationPanel(QWidget):
    """Panneau Investigation : composition UI sans accès repository ni logique métier."""

    selection_requested = Signal(object)
    file_requested = Signal(str)
    file_item_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = InvestigationTreeModel(self)
        self.tree = InvestigationTreeView(self.model, self)
        self._controller: InvestigationController | None = None
        self._selection_manager: SelectionManager | None = None
        self._integrity_report = IntegrityReport(())
        self.welcome_page = self._create_welcome_page()
        self.create_item_button = QPushButton("Créer un élément", self)
        self.create_case_button = QPushButton("Créer un dossier (Case)", self)
        self.create_collection_button = QPushButton("Créer une collection", self)
        self.create_post_it_button = QPushButton("Créer un Post-it", self)
        self.create_relation_button = QPushButton("Créer une relation", self)
        self.integrity_label = QLabel("", self)
        self.integrity_button = QPushButton("Consulter", self)
        self.integrity_button.setVisible(False)
        self.integrity_button.clicked.connect(self._show_integrity_report)
        integrity_layout = QHBoxLayout()
        integrity_layout.setContentsMargins(0, 0, 0, 0)
        integrity_layout.addWidget(self.integrity_label, 1)
        integrity_layout.addWidget(self.integrity_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(integrity_layout)
        creation_layout = QHBoxLayout()
        for button in (
            self.create_item_button,
            self.create_case_button,
            self.create_collection_button,
            self.create_post_it_button,
            self.create_relation_button,
        ):
            creation_layout.addWidget(button)
        creation_layout.addStretch()
        layout.addLayout(creation_layout)
        self.content_stack = QStackedWidget(self)
        self.content_stack.addWidget(self.welcome_page)
        self.content_stack.addWidget(self.tree)
        layout.addWidget(self.content_stack, 1)
        self.tree.section_expanded.connect(self._load_section)
        self.tree.entry_selected.connect(self._select_entry)
        self.tree.entry_activated.connect(self._activate_entry)
        self.tree.membership_requested.connect(self._add_dropped_membership)
        self.tree.context_menu_requested.connect(self._show_organization_menu)
        self.create_item_button.clicked.connect(self._create_item)
        self.create_case_button.clicked.connect(self._create_case)
        self.create_collection_button.clicked.connect(self._create_collection)
        self.create_post_it_button.clicked.connect(self._create_post_it)
        self.create_relation_button.clicked.connect(self._create_relation)

    def attach(
        self,
        service: InvestigationService,
        queries: InvestigationQueryService,
        validator: InvestigationIntegrityValidator,
        selection_manager: SelectionManager | None = None,
        entity_resolver: CanonicalEntityResolver | None = None,
    ) -> None:
        self.detach()
        self._controller = InvestigationController(service, queries, validator, self.model, entity_resolver, self)
        self._selection_manager = selection_manager
        self._controller.selection_requested.connect(self.selection_requested)
        self._controller.integrity_changed.connect(self._set_integrity_report)
        self._controller.item_presence_changed.connect(self._set_item_presence)
        self._controller.file_item_changed.connect(self.file_item_changed)
        self._set_integrity_report(self._controller.validate())
        self._set_item_presence(self._controller._has_tree_content())
        self._controller.refresh_section(InvestigationSection.JOURNAL)

    @property
    def service(self) -> InvestigationService | None:
        """Expose uniquement la façade de commandes du domaine aux contrôleurs UI."""
        return self._controller.service if self._controller is not None else None

    def detach(self) -> None:
        if self._controller is not None:
            self._controller.close()
            self._controller.deleteLater()
            self._controller = None
        self._selection_manager = None
        self.model.clear()
        self._set_integrity_report(IntegrityReport(()))
        self._set_item_presence(False)

    def _create_welcome_page(self) -> QWidget:
        page = QWidget(self)
        title = QLabel("Investigation", page)
        title.setObjectName("detailsTitle")
        description = QLabel(
            "Le module Investigation permet de structurer votre analyse comme un véritable dossier d'enquête.\n\n"
            "Vous pouvez créer des éléments d'investigation, les relier entre eux, écrire des notes, construire des "
            "hypothèses, organiser votre enquête en dossiers et collections, puis conserver un journal complet de vos actions.",
            page,
        )
        description.setWordWrap(True)
        layout = QVBoxLayout(page)
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addStretch()
        return page

    def _set_item_presence(self, has_items: bool) -> None:
        self.content_stack.setCurrentWidget(self.tree if has_items else self.welcome_page)

    def _create_item(self) -> None:
        dialog = ItemCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            item = self._controller.create_item(
                dialog.name_field.text(),
                dialog.description_field.toPlainText(),
                dialog.type_field.text(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._select_created_entry("item", str(item.item_id))

    def _create_note(self) -> None:
        dialog = NoteCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            note = self._controller.create_note(dialog.title_field.text(), dialog.body_field.toPlainText())
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._select_created_entry("note", str(note.note_id))

    def create_note_for_target(self, target_ref: InvestigationTargetRef) -> None:
        """Ouvre l'éditeur de note et rattache la note à une preuve existante."""
        dialog = NoteCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            note = self._controller.create_note(dialog.title_field.text(), dialog.body_field.toPlainText(), target_ref)
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._select_created_entry("note", str(note.note_id))

    def _create_hypothesis(self) -> None:
        dialog = HypothesisCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            hypothesis = self._controller.create_hypothesis(
                dialog.title_field.text(),
                dialog.description_field.toPlainText(),
                str(dialog.confidence_field.currentData()),
                str(dialog.status_field.currentData()),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._select_created_entry("hypothesis", str(hypothesis.hypothesis_id))

    def create_hypothesis_for_target(self, target_ref: InvestigationTargetRef) -> None:
        """Crée une hypothèse puis ajoute la preuve avec le rôle Observation."""
        dialog = HypothesisCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            hypothesis = self._controller.create_hypothesis(
                dialog.title_field.text(),
                dialog.description_field.toPlainText(),
                str(dialog.confidence_field.currentData()),
                str(dialog.status_field.currentData()),
                target_ref,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._select_created_entry("hypothesis", str(hypothesis.hypothesis_id))

    def _create_case(self) -> None:
        dialog = CaseCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            case = self._controller.create_case(dialog.name_field.text(), dialog.description_field.toPlainText())
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._select_created_entry("case", str(case.case_id))

    def _create_collection(self) -> None:
        dialog = CollectionCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            collection = self._controller.create_collection(
                dialog.name_field.text(), dialog.description_field.toPlainText()
            )
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._select_created_entry("collection", str(collection.collection_id))

    def _create_post_it(self) -> None:
        """Crée une note libre ; son rattachement reste une opération d'organisation."""
        dialog = NoteCreationDialog(self)
        dialog.setWindowTitle("Créer un Post-it")
        if dialog.exec() != dialog.DialogCode.Accepted or self._controller is None:
            return
        try:
            note = self._controller.create_note(dialog.title_field.text(), dialog.body_field.toPlainText())
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return

        self._select_created_entry("note", str(note.note_id))

    def _create_relation(self) -> None:
        if self._controller is None:
            return
        current = self._selection_manager.current if self._selection_manager is not None else None
        if current is None:
            return
        targets, relation_types = self._controller.relation_options()
        dialog = RelationCreationDialog(targets, relation_types, self)
        source_index = next(
            (
                row
                for row in range(dialog.source_field.count())
                if tuple(dialog.source_field.itemData(row)) == (current.subject_kind, current.subject_id)
            ),
            -1,
        )
        if source_index < 0:
            return
        dialog.source_field.setCurrentIndex(source_index)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            relation = self._controller.create_relation_command(
                tuple(dialog.source_field.currentData()),
                str(dialog.relation_type_field.currentData()),
                tuple(dialog.destination_field.currentData()),
            )
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self.selection_requested.emit(
            SelectionContext(
                relation.source_target.target_kind,
                relation.source_target.target_id,
                "investigation_relation",
            )
        )

    def _add_dropped_membership(self, source: InvestigationTreeEntry, target: InvestigationTreeEntry) -> None:
        if self._controller is None:
            return
        try:
            self._controller.organize_entry(source, target.subject_kind, target.subject_id)
        except ValueError as error:
            QMessageBox.warning(self, "Organisation impossible", str(error))
            return
        self.selection_requested.emit(
            SelectionContext(target.subject_kind, target.subject_id, "investigation_organization")
        )

    def _show_organization_menu(self, entry: InvestigationTreeEntry, position: QPoint) -> None:
        if self._controller is None or entry.subject_kind not in {"item", "note", "hypothesis"}:
            return
        self._organization_menu(entry).exec(position)

    def _organization_menu(self, entry: InvestigationTreeEntry) -> QMenu:
        """Construit le menu contextuel ; isolé pour rester testable sans boucle modale."""
        menu = QMenu(self)
        case_action = menu.addAction("Ajouter à une Case...")
        collection_action = menu.addAction("Ajouter à une Collection...")
        case_action.triggered.connect(lambda: self._choose_container(entry, "case"))
        collection_action.triggered.connect(lambda: self._choose_container(entry, "collection"))
        return menu

    def _choose_container(self, entry: InvestigationTreeEntry, container_kind: str) -> None:
        if self._controller is None:
            return
        is_case = container_kind == "case"
        dialog = MembershipSelectionDialog(
            "Ajouter à une Case" if is_case else "Ajouter à une Collection",
            "Case" if is_case else "Collection",
            self._controller.container_options(container_kind),
            self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self._controller.organize_entry(entry, container_kind, str(dialog.container_field.currentData()))
        except ValueError as error:
            QMessageBox.warning(self, "Organisation impossible", str(error))

    def _select_created_entry(self, subject_kind: str, subject_id: str) -> None:
        index = self.model.index_for_entry(subject_kind, subject_id)
        if not index.isValid():
            return
        self.tree.expand(index.parent())
        if self.tree.currentIndex() == index:
            entry = self.model.entry_for_index(index)
            if entry is not None:
                self._select_entry(entry)
            return
        self.tree.setCurrentIndex(index)
        self.tree.scrollTo(index)

    def _load_section(self, section: InvestigationSection) -> None:
        if self._controller is not None:
            self._controller.load_section(section)

    def _select_entry(self, entry: InvestigationTreeEntry) -> None:
        if self._controller is not None:
            self._controller.select_entry(entry)

    def _activate_entry(self, entry: InvestigationTreeEntry) -> None:
        target = entry.related_target_ref
        if entry.subject_kind == "item" and target is not None and target.target_kind == "file":
            self.file_requested.emit(target.target_id)

    def select_item(self, item_id: str) -> None:
        """Expose une navigation UI après une commande externe au panneau."""
        self._select_created_entry("item", item_id)

    def add_file_item(self, file_id: str, title: str):
        """Commande publique de l'UI Fichiers, relayée exclusivement au service."""
        if self._controller is None:
            return None
        item = self._controller.add_file_item(file_id, title)
        self.select_item(str(item.item_id))
        return item

    def add_target_item(self, target: InvestigationTargetRef, title: str):
        if self._controller is None:
            return None
        item = self._controller.add_target_item(target, title)
        self.select_item(str(item.item_id))
        return item

    def edit_evidence(
        self,
        target: InvestigationTargetRef,
        *,
        original_name: str,
        evidence_type: str = "",
        sha256: str = "",
    ):
        """Ouvre le formulaire de preuve ; le contrôleur porte seul les commandes."""
        if self._controller is None:
            return None
        context = self._controller.evidence_context(target, original_name)
        dialog = EvidenceDialog(
            display_name=context.display_name,
            original_name=original_name,
            evidence_type=evidence_type,
            sha256=sha256,
            note=context.note,
            hypothesis=context.hypothesis,
            cases=context.cases,
            collections=context.collections,
            selected_case_id=context.selected_case_id,
            selected_collection_id=context.selected_collection_id,
            already_present=context.existing,
            parent=self,
        )
        dialog.new_case_button.clicked.connect(lambda: self._create_evidence_container(dialog, "case"))
        dialog.new_collection_button.clicked.connect(lambda: self._create_evidence_container(dialog, "collection"))
        if dialog.exec() != dialog.DialogCode.Accepted:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            item = self._controller.apply_evidence(
                target,
                display_name=dialog.name_field.text().strip(),
                note=dialog.note_field.toPlainText(),
                hypothesis=dialog.hypothesis_field.text(),
                case_id=dialog.case_field.currentData(),
                collection_id=dialog.collection_field.currentData(),
            )
        except (KeyError, ValueError) as error:
            QMessageBox.warning(self, "Enregistrement impossible", str(error))
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.select_item(str(item.item_id))
        return item

    def _create_evidence_container(self, evidence_dialog: EvidenceDialog, kind: str) -> None:
        if self._controller is None:
            return
        dialog = CaseCreationDialog(self) if kind == "case" else CollectionCreationDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            container = (
                self._controller.create_case(dialog.name_field.text(), dialog.description_field.toPlainText())
                if kind == "case"
                else self._controller.create_collection(
                    dialog.name_field.text(), dialog.description_field.toPlainText()
                )
            )
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        if kind == "case":
            evidence_dialog.add_case(container.title, str(container.case_id))
        else:
            evidence_dialog.add_collection(container.title, str(container.collection_id))

    def has_file_item(self, file_id: str) -> bool:
        if self._controller is None:
            return False
        return self._controller.has_file_item(file_id)

    def has_target_item(self, target: InvestigationTargetRef) -> bool:
        return self._controller is not None and self._controller.has_target_item(target)

    def _set_integrity_report(self, report: IntegrityReport) -> None:
        self._integrity_report = report
        count = len(report.issues)
        self.integrity_label.setText("" if not count else f"⚠ {count} anomalie(s) d'intégrité détectée(s).")
        self.integrity_button.setVisible(bool(count))

    def _show_integrity_report(self) -> None:
        lines = [
            f"[{issue.severity.value.upper()}] {issue.code} — {issue.description}"
            for issue in self._integrity_report.issues
        ]
        QMessageBox.warning(self, "Intégrité Investigation", "\n".join(lines) or "Aucune anomalie détectée.")
