"""Façade applicative du module Investigation."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from core.batch import BatchOperationResult
from investigation.case import (
    CaseMembership,
    CaseMembershipId,
    CasePriority,
    CaseStatus,
    InvestigationCase,
    InvestigationCaseId,
)
from investigation.collection import (
    CollectionMembership,
    CollectionMembershipId,
    InvestigationCollection,
    InvestigationCollectionId,
)
from investigation.events import EventBus, EventPublisher, EventType, InvestigationEvent
from investigation.hypothesis import (
    HypothesisConfidence,
    HypothesisMembership,
    HypothesisMembershipId,
    HypothesisRole,
    HypothesisStatus,
    InvestigationHypothesis,
    InvestigationHypothesisId,
)
from investigation.item import InvestigationItem, InvestigationItemId, InvestigationPriority, InvestigationStatus
from investigation.journal import InvestigationJournalEntry
from investigation.manager import InvestigationManager
from investigation.note import InvestigationNote, InvestigationNoteFormat, InvestigationNoteId
from investigation.relation import InvestigationRelation, InvestigationRelationId, InvestigationRelationType
from investigation.tag import InvestigationTag, InvestigationTagId, TagAssignment, TagAssignmentId, normalize_tag_name
from investigation.target_ref import InvestigationTargetRef
from utils import performance


class InvestigationService:
    """Point d'entrée unique des futures commandes Investigation.

    Il ne contient volontairement aucune opération sur cases, hypothèses,
    collections, notes, tags, relations ou journal durant la phase 1.
    """

    def __init__(self, manager: InvestigationManager, events: EventPublisher | None = None) -> None:
        self._manager = manager
        self._events = events or EventBus()

    @property
    def is_open(self) -> bool:
        return self._manager.is_open

    @property
    def manager(self) -> InvestigationManager:
        return self._manager

    @property
    def event_publisher(self) -> EventPublisher:
        return self._events

    @property
    def event_bus(self) -> EventBus | None:
        """Bus local lorsqu'il est utilisé ; permet l'abonnement des consommateurs."""
        return self._events if isinstance(self._events, EventBus) else None

    def _publish(
        self,
        event_type: EventType,
        entity_id: str,
        *,
        target_ref: InvestigationTargetRef | None = None,
        related_target_ref: InvestigationTargetRef | None = None,
        parent_kind: str | None = None,
        parent_id: str | None = None,
        created_by: str | None = None,
    ) -> None:
        self._events.publish(
            InvestigationEvent(
                event_type=event_type,
                entity_id=entity_id,
                target_ref=target_ref,
                related_target_ref=related_target_ref,
                parent_kind=parent_kind,
                parent_id=parent_id,
                created_by=created_by,
            )
        )

    def open(self) -> None:
        self._manager.open()

    def close(self) -> None:
        self._manager.close()

    def save(self) -> None:
        self._manager.save()

    def create_item(
        self,
        subject_kind: str,
        subject_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        priority: InvestigationPriority = InvestigationPriority.INFORMATION,
        status: InvestigationStatus = InvestigationStatus.NEW,
        created_by: str | None = None,
    ) -> InvestigationItem:
        item = InvestigationItem(
            item_id=InvestigationItemId(str(uuid4())),
            subject_kind=subject_kind,
            subject_id=subject_id,
            title=title,
            summary=summary,
            priority=priority,
            status=status,
            created_by=created_by,
            updated_by=created_by,
        )
        created = self._manager.create_item(item)
        self._publish(
            EventType.ITEM_CREATED,
            str(created.item_id),
            target_ref=InvestigationTargetRef(created.subject_kind, created.subject_id),
            created_by=created.created_by,
        )
        return created

    def create_items_batch(
        self,
        subjects: tuple[InvestigationTargetRef, ...],
        *,
        created_by: str | None = None,
    ) -> BatchOperationResult[InvestigationItem]:
        """Crée les preuves absentes pour une sélection, en une seule commande.

        Les sujets dupliqués et les preuves déjà présentes sont ignorés. Un
        unique événement de fin est publié uniquement après la cohérence de
        l'index et du repository.
        """
        with performance.measure("InvestigationService.create_items_batch.prepare", requested=len(subjects)):
            unique = tuple(dict.fromkeys(subjects))
            skipped: list[InvestigationItem] = []
            candidates: list[InvestigationItem] = []
            for subject in unique:
                existing = self._manager.find_item_by_subject(subject.target_kind, subject.target_id)
                if existing is not None:
                    skipped.append(existing)
                    continue
                candidates.append(
                    InvestigationItem(
                        item_id=InvestigationItemId(str(uuid4())),
                        subject_kind=subject.target_kind,
                        subject_id=subject.target_id,
                        created_by=created_by,
                        updated_by=created_by,
                    )
                )
        with performance.measure("InvestigationService.create_items_batch.mutation", candidates=len(candidates)):
            created = self._manager.create_items_batch(tuple(candidates))
        result = BatchOperationResult(len(subjects), created, tuple(skipped))
        with performance.measure("InvestigationService.create_items_batch.publish", created=len(created)):
            self._publish(
                EventType.BATCH_COMPLETED,
                result.operation_id,
                parent_kind="items",
                parent_id="items",
                created_by=created_by,
            )
        return result

    def update_item(self, item: InvestigationItem) -> InvestigationItem:
        updated = self._manager.update_item(item)
        self._publish(
            EventType.ITEM_UPDATED,
            str(updated.item_id),
            target_ref=InvestigationTargetRef(updated.subject_kind, updated.subject_id),
        )
        return updated

    def delete_item(self, item_id: InvestigationItemId) -> None:
        item = self._manager.get_item(item_id)
        self._manager.delete_item(item_id)
        assert item is not None
        self._publish(
            EventType.ITEM_DELETED, str(item_id), target_ref=InvestigationTargetRef(item.subject_kind, item.subject_id)
        )

    def get_item(self, item_id: InvestigationItemId) -> InvestigationItem | None:
        return self._manager.get_item(item_id)

    def find_item_by_subject(self, subject_kind: str, subject_id: str) -> InvestigationItem | None:
        return self._manager.find_item_by_subject(subject_kind, subject_id)

    def list_items(self) -> tuple[InvestigationItem, ...]:
        return self._manager.list_items()

    def list_entries(self) -> tuple[InvestigationJournalEntry, ...]:
        return self._manager.list_journal_entries()

    def find_entries_for_target(self, target_ref: InvestigationTargetRef) -> tuple[InvestigationJournalEntry, ...]:
        return self._manager.find_journal_entries_for_target(target_ref)

    def find_entries_by_event_type(self, event_type: EventType) -> tuple[InvestigationJournalEntry, ...]:
        return self._manager.find_journal_entries_by_event_type(event_type)

    def find_entries_between_dates(self, start: datetime, end: datetime) -> tuple[InvestigationJournalEntry, ...]:
        return self._manager.find_journal_entries_between_dates(start, end)

    def create_collection(
        self,
        title: str,
        *,
        description: str | None = None,
        created_by: str | None = None,
    ) -> InvestigationCollection:
        collection = InvestigationCollection(
            collection_id=InvestigationCollectionId(str(uuid4())),
            title=title,
            description=description,
            created_by=created_by,
        )
        created = self._manager.create_collection(collection)
        self._publish(EventType.COLLECTION_CREATED, str(created.collection_id), created_by=created.created_by)
        return created

    def update_collection(self, collection: InvestigationCollection) -> InvestigationCollection:
        updated = self._manager.update_collection(collection)
        self._publish(EventType.COLLECTION_UPDATED, str(updated.collection_id))
        return updated

    def delete_collection(self, collection_id: InvestigationCollectionId) -> None:
        self._manager.delete_collection(collection_id)
        self._publish(EventType.COLLECTION_DELETED, str(collection_id))

    def get_collection(self, collection_id: InvestigationCollectionId) -> InvestigationCollection | None:
        return self._manager.get_collection(collection_id)

    def list_collections(self) -> tuple[InvestigationCollection, ...]:
        return self._manager.list_collections()

    def add_to_collection(
        self,
        collection_id: InvestigationCollectionId,
        target_ref: InvestigationTargetRef,
        *,
        added_by: str | None = None,
    ) -> CollectionMembership:
        membership = CollectionMembership(
            membership_id=CollectionMembershipId(str(uuid4())),
            collection_id=collection_id,
            target_ref=target_ref,
            added_by=added_by,
        )
        created = self._manager.add_to_collection(membership)
        self._publish(
            EventType.MEMBERSHIP_ADDED,
            str(created.membership_id),
            target_ref=created.target_ref,
            parent_kind="collection",
            parent_id=str(created.collection_id),
        )
        return created

    def add_files_to_collection_batch(
        self,
        collection_id: InvestigationCollectionId,
        file_ids: tuple[str, ...],
        *,
        added_by: str | None = None,
    ) -> BatchOperationResult[CollectionMembership]:
        """Crée/réutilise les preuves fichier puis les rattache à une Collection.

        Cette commande est l'unité logique employée par l'UI de sélection de
        masse : pas d'appel unitaire ni de publication par fichier.
        """
        unique_ids = tuple(dict.fromkeys(file_id for file_id in file_ids if file_id))
        targets = tuple(InvestigationTargetRef("file", file_id) for file_id in unique_ids)
        missing_items = tuple(
            InvestigationItem(
                item_id=InvestigationItemId(str(uuid4())),
                subject_kind=target.target_kind,
                subject_id=target.target_id,
                created_by=added_by,
                updated_by=added_by,
            )
            for target in targets
            if self._manager.find_item_by_subject(target.target_kind, target.target_id) is None
        )
        # Les Items doivent exister avant de produire les références de membership.
        created_items = self._manager.create_items_batch(missing_items)
        item_refs = tuple(
            InvestigationTargetRef(
                "item", str(self._manager.find_item_by_subject(target.target_kind, target.target_id).item_id)
            )
            for target in targets
        )
        existing_members = set(self._manager.find_collection_members(collection_id))
        memberships = tuple(
            CollectionMembership(
                membership_id=CollectionMembershipId(str(uuid4())),
                collection_id=collection_id,
                target_ref=item_ref,
                added_by=added_by,
            )
            for item_ref in item_refs
            if item_ref not in existing_members
        )
        try:
            created_memberships = self._manager.add_to_collection_batch(memberships)
        except Exception:
            # Les nouvelles preuves font partie de la même transaction logique
            # que leurs memberships : aucune ne subsiste si le rattachement
            # échoue. Les preuves préexistantes ne sont jamais touchées.
            for item in created_items:
                self._manager.delete_item(item.item_id)
            raise
        skipped = tuple(
            membership
            for membership in (
                CollectionMembership(
                    membership_id=CollectionMembershipId(str(uuid4())),
                    collection_id=collection_id,
                    target_ref=item_ref,
                    added_by=added_by,
                )
                for item_ref in item_refs
            )
            if membership.target_ref in existing_members
        )
        result = BatchOperationResult(len(file_ids), created_memberships, skipped)
        self._publish(
            EventType.BATCH_COMPLETED,
            result.operation_id,
            parent_kind="collection",
            parent_id=str(collection_id),
            created_by=added_by,
        )
        return result

    def remove_from_collection(
        self, collection_id: InvestigationCollectionId, target_ref: InvestigationTargetRef
    ) -> None:
        self._manager.remove_from_collection(collection_id, target_ref)
        self._publish(
            EventType.MEMBERSHIP_REMOVED,
            str(collection_id),
            target_ref=target_ref,
            parent_kind="collection",
            parent_id=str(collection_id),
        )

    def add_items_to_collection_batch(
        self,
        collection_id: InvestigationCollectionId,
        item_ids: tuple[str, ...],
        *,
        added_by: str | None = None,
    ) -> BatchOperationResult[CollectionMembership]:
        """Rattache les preuves Investigation existantes à une Collection."""
        targets = self._item_targets(item_ids)
        existing = set(self._manager.find_collection_members(collection_id))
        memberships = tuple(
            CollectionMembership(
                membership_id=CollectionMembershipId(str(uuid4())),
                collection_id=collection_id,
                target_ref=target,
                added_by=added_by,
            )
            for target in targets
            if target not in existing
        )
        created = self._manager.add_to_collection_batch(memberships)
        skipped = tuple(
            CollectionMembership(
                membership_id=CollectionMembershipId(str(uuid4())),
                collection_id=collection_id,
                target_ref=target,
                added_by=added_by,
            )
            for target in targets
            if target in existing
        )
        result = BatchOperationResult(len(item_ids), created, skipped)
        self._publish(
            EventType.BATCH_COMPLETED,
            result.operation_id,
            parent_kind="collection",
            parent_id=str(collection_id),
            created_by=added_by,
        )
        return result

    def find_collection_members(self, collection_id: InvestigationCollectionId) -> tuple[InvestigationTargetRef, ...]:
        return self._manager.find_collection_members(collection_id)

    def find_collections_for_target(self, target_ref: InvestigationTargetRef) -> tuple[InvestigationCollection, ...]:
        return self._manager.find_collections_for_target(target_ref)

    def create_hypothesis(
        self,
        title: str,
        *,
        description: str | None = None,
        status: HypothesisStatus = HypothesisStatus.DRAFT,
        confidence: HypothesisConfidence = HypothesisConfidence.UNKNOWN,
        created_by: str | None = None,
    ) -> InvestigationHypothesis:
        hypothesis = InvestigationHypothesis(
            hypothesis_id=InvestigationHypothesisId(str(uuid4())),
            title=title,
            description=description,
            status=status,
            confidence=confidence,
            created_by=created_by,
        )
        created = self._manager.create_hypothesis(hypothesis)
        self._publish(EventType.HYPOTHESIS_CREATED, str(created.hypothesis_id), created_by=created.created_by)
        return created

    def update_hypothesis(self, hypothesis: InvestigationHypothesis) -> InvestigationHypothesis:
        updated = self._manager.update_hypothesis(hypothesis)
        self._publish(EventType.HYPOTHESIS_UPDATED, str(updated.hypothesis_id))
        return updated

    def delete_hypothesis(self, hypothesis_id: InvestigationHypothesisId) -> None:
        self._manager.delete_hypothesis(hypothesis_id)
        self._publish(EventType.HYPOTHESIS_DELETED, str(hypothesis_id))

    def get_hypothesis(self, hypothesis_id: InvestigationHypothesisId) -> InvestigationHypothesis | None:
        return self._manager.get_hypothesis(hypothesis_id)

    def list_hypotheses(self) -> tuple[InvestigationHypothesis, ...]:
        return self._manager.list_hypotheses()

    def add_to_hypothesis(
        self,
        hypothesis_id: InvestigationHypothesisId,
        target_ref: InvestigationTargetRef,
        role: HypothesisRole,
        *,
        added_by: str | None = None,
    ) -> HypothesisMembership:
        membership = HypothesisMembership(
            membership_id=HypothesisMembershipId(str(uuid4())),
            hypothesis_id=hypothesis_id,
            target_ref=target_ref,
            role=role,
            added_by=added_by,
        )
        created = self._manager.add_to_hypothesis(membership)
        self._publish(
            EventType.MEMBERSHIP_ADDED,
            str(created.membership_id),
            target_ref=created.target_ref,
            parent_kind="hypothesis",
            parent_id=str(created.hypothesis_id),
        )
        return created

    def remove_from_hypothesis(
        self, hypothesis_id: InvestigationHypothesisId, target_ref: InvestigationTargetRef
    ) -> None:
        self._manager.remove_from_hypothesis(hypothesis_id, target_ref)
        self._publish(
            EventType.MEMBERSHIP_REMOVED,
            str(hypothesis_id),
            target_ref=target_ref,
            parent_kind="hypothesis",
            parent_id=str(hypothesis_id),
        )

    def find_hypothesis_members(self, hypothesis_id: InvestigationHypothesisId) -> tuple[InvestigationTargetRef, ...]:
        return self._manager.find_hypothesis_members(hypothesis_id)

    def find_hypothesis_memberships(self, hypothesis_id: InvestigationHypothesisId) -> tuple[HypothesisMembership, ...]:
        """Expose les rôles des membres sans révéler les index internes du manager."""
        return self._manager.find_hypothesis_memberships(hypothesis_id)

    def find_hypotheses_for_target(self, target_ref: InvestigationTargetRef) -> tuple[InvestigationHypothesis, ...]:
        return self._manager.find_hypotheses_for_target(target_ref)

    def create_relation(
        self,
        source_target: InvestigationTargetRef,
        destination_target: InvestigationTargetRef,
        relation_type: InvestigationRelationType,
        *,
        comment: str | None = None,
        created_by: str | None = None,
    ) -> InvestigationRelation:
        relation = InvestigationRelation(
            relation_id=InvestigationRelationId(str(uuid4())),
            source_target=source_target,
            destination_target=destination_target,
            relation_type=relation_type,
            comment=comment,
            created_by=created_by,
            updated_by=created_by,
        )
        created = self._manager.create_relation(relation)
        self._publish(
            EventType.RELATION_CREATED,
            str(created.relation_id),
            target_ref=created.source_target,
            related_target_ref=created.destination_target,
        )
        return created

    def update_relation(self, relation: InvestigationRelation) -> InvestigationRelation:
        return self._manager.update_relation(relation)

    def delete_relation(self, relation_id: InvestigationRelationId) -> None:
        relation = self._manager.get_relation(relation_id)
        self._manager.delete_relation(relation_id)
        assert relation is not None
        self._publish(
            EventType.RELATION_DELETED,
            str(relation_id),
            target_ref=relation.source_target,
            related_target_ref=relation.destination_target,
        )

    def get_relation(self, relation_id: InvestigationRelationId) -> InvestigationRelation | None:
        return self._manager.get_relation(relation_id)

    def list_relations(self) -> tuple[InvestigationRelation, ...]:
        return self._manager.list_relations()

    def find_relations_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationRelation, ...]:
        return self._manager.find_relations_for_target(target)

    def create_note(
        self,
        body: str,
        *,
        target_ref: InvestigationTargetRef | None = None,
        format: InvestigationNoteFormat = InvestigationNoteFormat.PLAIN_TEXT,
        author: str | None = None,
    ) -> InvestigationNote:
        note = InvestigationNote(
            note_id=InvestigationNoteId(str(uuid4())),
            target_ref=target_ref,
            body=body,
            format=format,
            author=author,
        )
        created = self._manager.create_note(note)
        self._publish(
            EventType.NOTE_CREATED, str(created.note_id), target_ref=created.target_ref, created_by=created.author
        )
        return created

    def update_note(self, note: InvestigationNote) -> InvestigationNote:
        updated = self._manager.update_note(note)
        self._publish(EventType.NOTE_UPDATED, str(updated.note_id), target_ref=updated.target_ref)
        return updated

    def delete_note(self, note_id: InvestigationNoteId) -> None:
        note = self._manager.get_note(note_id)
        self._manager.delete_note(note_id)
        assert note is not None
        self._publish(EventType.NOTE_DELETED, str(note_id), target_ref=note.target_ref)

    def get_note(self, note_id: InvestigationNoteId) -> InvestigationNote | None:
        return self._manager.get_note(note_id)

    def list_notes(self) -> tuple[InvestigationNote, ...]:
        return self._manager.list_notes()

    def find_notes_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationNote, ...]:
        return self._manager.find_notes_for_target(target)

    def create_tag(
        self,
        display_name: str,
        *,
        color: str | None = None,
        description: str | None = None,
    ) -> InvestigationTag:
        tag = InvestigationTag(
            tag_id=InvestigationTagId(str(uuid4())),
            normalized_name=normalize_tag_name(display_name),
            display_name=display_name,
            color=color,
            description=description,
        )
        created = self._manager.create_tag(tag)
        self._publish(EventType.TAG_CREATED, str(created.tag_id))
        return created

    def update_tag(self, tag: InvestigationTag) -> InvestigationTag:
        updated = self._manager.update_tag(tag)
        self._publish(EventType.TAG_UPDATED, str(updated.tag_id))
        return updated

    def delete_tag(self, tag_id: InvestigationTagId) -> None:
        self._manager.delete_tag(tag_id)
        self._publish(EventType.TAG_DELETED, str(tag_id))

    def get_tag(self, tag_id: InvestigationTagId) -> InvestigationTag | None:
        return self._manager.get_tag(tag_id)

    def list_tags(self) -> tuple[InvestigationTag, ...]:
        return self._manager.list_tags()

    def assign_tag(
        self,
        tag_id: InvestigationTagId,
        target_ref: InvestigationTargetRef,
        *,
        assigned_by: str | None = None,
    ) -> TagAssignment:
        assignment = TagAssignment(
            assignment_id=TagAssignmentId(str(uuid4())),
            tag_id=tag_id,
            target_ref=target_ref,
            assigned_by=assigned_by,
        )
        created = self._manager.assign_tag(assignment)
        self._publish(
            EventType.MEMBERSHIP_ADDED,
            str(created.assignment_id),
            target_ref=created.target_ref,
            parent_kind="tag",
            parent_id=str(created.tag_id),
        )
        return created

    def unassign_tag(self, tag_id: InvestigationTagId, target_ref: InvestigationTargetRef) -> None:
        self._manager.unassign_tag(tag_id, target_ref)
        self._publish(
            EventType.MEMBERSHIP_REMOVED,
            str(tag_id),
            target_ref=target_ref,
            parent_kind="tag",
            parent_id=str(tag_id),
        )

    def find_tags_for_target(self, target_ref: InvestigationTargetRef) -> tuple[InvestigationTag, ...]:
        return self._manager.find_tags_for_target(target_ref)

    def find_targets_for_tag(self, tag_id: InvestigationTagId) -> tuple[InvestigationTargetRef, ...]:
        return self._manager.find_targets_for_tag(tag_id)

    def tag_usage_count(self, tag_id: InvestigationTagId) -> int:
        return self._manager.tag_usage_count(tag_id)

    def create_case(
        self,
        title: str,
        *,
        description: str | None = None,
        status: CaseStatus = CaseStatus.OPEN,
        priority: CasePriority = CasePriority.INFORMATION,
        created_by: str | None = None,
    ) -> InvestigationCase:
        case = InvestigationCase(
            case_id=InvestigationCaseId(str(uuid4())),
            title=title,
            description=description,
            status=status,
            priority=priority,
            created_by=created_by,
        )
        created = self._manager.create_case(case)
        self._publish(EventType.CASE_CREATED, str(created.case_id), created_by=created.created_by)
        return created

    def update_case(self, case: InvestigationCase) -> InvestigationCase:
        updated = self._manager.update_case(case)
        self._publish(EventType.CASE_UPDATED, str(updated.case_id))
        return updated

    def delete_case(self, case_id: InvestigationCaseId) -> None:
        self._manager.delete_case(case_id)
        self._publish(EventType.CASE_DELETED, str(case_id))

    def get_case(self, case_id: InvestigationCaseId) -> InvestigationCase | None:
        return self._manager.get_case(case_id)

    def list_cases(self) -> tuple[InvestigationCase, ...]:
        return self._manager.list_cases()

    def add_to_case(
        self,
        case_id: InvestigationCaseId,
        target_ref: InvestigationTargetRef,
        *,
        added_by: str | None = None,
    ) -> CaseMembership:
        membership = CaseMembership(
            membership_id=CaseMembershipId(str(uuid4())),
            case_id=case_id,
            target_ref=target_ref,
            added_by=added_by,
        )
        created = self._manager.add_to_case(membership)
        self._publish(
            EventType.MEMBERSHIP_ADDED,
            str(created.membership_id),
            target_ref=created.target_ref,
            parent_kind="case",
            parent_id=str(created.case_id),
        )
        return created

    def add_items_to_case_batch(
        self,
        case_id: InvestigationCaseId,
        item_ids: tuple[str, ...],
        *,
        added_by: str | None = None,
    ) -> BatchOperationResult[CaseMembership]:
        """Rattache les preuves Investigation existantes à une Case."""
        targets = self._item_targets(item_ids)
        existing = set(self._manager.find_case_members(case_id))
        memberships = tuple(
            CaseMembership(
                membership_id=CaseMembershipId(str(uuid4())),
                case_id=case_id,
                target_ref=target,
                added_by=added_by,
            )
            for target in targets
            if target not in existing
        )
        created = self._manager.add_to_case_batch(memberships)
        skipped = tuple(
            CaseMembership(
                membership_id=CaseMembershipId(str(uuid4())),
                case_id=case_id,
                target_ref=target,
                added_by=added_by,
            )
            for target in targets
            if target in existing
        )
        result = BatchOperationResult(len(item_ids), created, skipped)
        self._publish(
            EventType.BATCH_COMPLETED,
            result.operation_id,
            parent_kind="case",
            parent_id=str(case_id),
            created_by=added_by,
        )
        return result

    def remove_from_case(self, case_id: InvestigationCaseId, target_ref: InvestigationTargetRef) -> None:
        self._manager.remove_from_case(case_id, target_ref)
        self._publish(
            EventType.MEMBERSHIP_REMOVED,
            str(case_id),
            target_ref=target_ref,
            parent_kind="case",
            parent_id=str(case_id),
        )

    def find_case_members(self, case_id: InvestigationCaseId) -> tuple[InvestigationTargetRef, ...]:
        return self._manager.find_case_members(case_id)

    def _item_targets(self, item_ids: tuple[str, ...]) -> tuple[InvestigationTargetRef, ...]:
        """Valide et déduplique les preuves à organiser, dans l'ordre utilisateur."""
        unique_ids = tuple(dict.fromkeys(item_id for item_id in item_ids if item_id))
        for item_id in unique_ids:
            if self._manager.get_item(InvestigationItemId(item_id)) is None:
                raise KeyError(f"InvestigationItem introuvable : {item_id}")
        return tuple(InvestigationTargetRef("item", item_id) for item_id in unique_ids)

    def find_cases_for_target(self, target_ref: InvestigationTargetRef) -> tuple[InvestigationCase, ...]:
        return self._manager.find_cases_for_target(target_ref)
