"""Cycle de vie métier du module Investigation."""

from __future__ import annotations

from datetime import datetime

from investigation.case import CaseMembership, CaseMembershipId, InvestigationCase, InvestigationCaseId
from investigation.collection import (
    CollectionMembership,
    CollectionMembershipId,
    InvestigationCollection,
    InvestigationCollectionId,
)
from investigation.events import EventType
from investigation.hypothesis import (
    HypothesisMembership,
    HypothesisMembershipId,
    HypothesisRole,
    InvestigationHypothesis,
    InvestigationHypothesisId,
)
from investigation.item import InvestigationItem, InvestigationItemId
from investigation.journal import InvestigationJournalEntry, InvestigationJournalEntryId
from investigation.note import InvestigationNote, InvestigationNoteId
from investigation.relation import InvestigationRelation, InvestigationRelationId, InvestigationRelationType
from investigation.repository import InvestigationRepository
from investigation.tag import InvestigationTag, InvestigationTagId, TagAssignment, TagAssignmentId
from investigation.target_ref import InvestigationTargetRef


class InvestigationManager:
    """Coordonne le module sans dépendre d'une vue, de Qt ou d'un autre module.

    Les futurs agrégats et index seront ajoutés ici par phases. À ce stade, le
    manager établit seulement l'état ouvert/fermé du contexte de projet.
    """

    def __init__(self, repository: InvestigationRepository) -> None:
        self._repository = repository
        self._is_open = False
        self._items_by_id: dict[InvestigationItemId, InvestigationItem] = {}
        self._item_id_by_subject: dict[tuple[str, str], InvestigationItemId] = {}
        self._collections_by_id: dict[InvestigationCollectionId, InvestigationCollection] = {}
        self._collection_memberships_by_id: dict[CollectionMembershipId, CollectionMembership] = {}
        self._collection_ids_by_target: dict[InvestigationTargetRef, set[InvestigationCollectionId]] = {}
        self._targets_by_collection: dict[InvestigationCollectionId, set[InvestigationTargetRef]] = {}
        self._collection_membership_id_by_pair: dict[
            tuple[InvestigationCollectionId, InvestigationTargetRef], CollectionMembershipId
        ] = {}
        self._hypotheses_by_id: dict[InvestigationHypothesisId, InvestigationHypothesis] = {}
        self._hypothesis_memberships_by_id: dict[HypothesisMembershipId, HypothesisMembership] = {}
        self._hypothesis_ids_by_target: dict[InvestigationTargetRef, set[InvestigationHypothesisId]] = {}
        self._targets_by_hypothesis: dict[InvestigationHypothesisId, set[InvestigationTargetRef]] = {}
        self._hypothesis_membership_ids_by_role: dict[HypothesisRole, set[HypothesisMembershipId]] = {}
        self._hypothesis_membership_id_by_pair: dict[
            tuple[InvestigationHypothesisId, InvestigationTargetRef], HypothesisMembershipId
        ] = {}
        self._journal_entries_by_id: dict[InvestigationJournalEntryId, InvestigationJournalEntry] = {}
        self._journal_entry_ids_by_timestamp: dict[datetime, set[InvestigationJournalEntryId]] = {}
        self._journal_entry_ids_by_event_type: dict[EventType, set[InvestigationJournalEntryId]] = {}
        self._journal_entry_ids_by_target: dict[InvestigationTargetRef, set[InvestigationJournalEntryId]] = {}
        self._relations_by_id: dict[InvestigationRelationId, InvestigationRelation] = {}
        self._relation_ids_by_source: dict[InvestigationTargetRef, set[InvestigationRelationId]] = {}
        self._relation_ids_by_destination: dict[InvestigationTargetRef, set[InvestigationRelationId]] = {}
        self._relation_ids_by_type: dict[InvestigationRelationType, set[InvestigationRelationId]] = {}
        self._relation_id_by_signature: dict[
            tuple[InvestigationRelationType, InvestigationTargetRef, InvestigationTargetRef], InvestigationRelationId
        ] = {}
        self._notes_by_id: dict[InvestigationNoteId, InvestigationNote] = {}
        self._note_ids_by_target: dict[InvestigationTargetRef, set[InvestigationNoteId]] = {}
        self._note_ids_by_author: dict[str | None, set[InvestigationNoteId]] = {}
        self._tags_by_id: dict[InvestigationTagId, InvestigationTag] = {}
        self._tag_id_by_normalized_name: dict[str, InvestigationTagId] = {}
        self._assignments_by_id: dict[TagAssignmentId, TagAssignment] = {}
        self._tag_ids_by_target: dict[InvestigationTargetRef, set[InvestigationTagId]] = {}
        self._targets_by_tag: dict[InvestigationTagId, set[InvestigationTargetRef]] = {}
        self._assignment_id_by_pair: dict[tuple[InvestigationTagId, InvestigationTargetRef], TagAssignmentId] = {}
        self._cases_by_id: dict[InvestigationCaseId, InvestigationCase] = {}
        self._case_memberships_by_id: dict[CaseMembershipId, CaseMembership] = {}
        self._case_ids_by_target: dict[InvestigationTargetRef, set[InvestigationCaseId]] = {}
        self._targets_by_case: dict[InvestigationCaseId, set[InvestigationTargetRef]] = {}
        self._case_membership_id_by_pair: dict[tuple[InvestigationCaseId, InvestigationTargetRef], CaseMembershipId] = (
            {}
        )

    @property
    def repository(self) -> InvestigationRepository:
        return self._repository

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        self.rebuild_indexes()
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def save(self) -> None:
        """Point d'extension avant le flush projet ; aucune donnée en phase 1."""
        if not self._is_open:
            raise RuntimeError("Le module Investigation doit être ouvert avant sauvegarde.")

    def create_item(self, item: InvestigationItem) -> InvestigationItem:
        self._require_open()
        if item.item_id in self._items_by_id:
            raise ValueError(f"InvestigationItem déjà existant : {item.item_id}")
        if item.subject_ref in self._item_id_by_subject:
            raise ValueError("Un InvestigationItem existe déjà pour ce sujet.")
        self._repository.create_item(item)
        self._index_item(item)
        return item

    def create_items_batch(self, items: tuple[InvestigationItem, ...]) -> tuple[InvestigationItem, ...]:
        """Crée un ensemble d'Items après validation complète, sans état intermédiaire."""
        self._require_open()
        item_ids: set[InvestigationItemId] = set()
        subjects: set[tuple[str, str]] = set()
        for item in items:
            if item.item_id in item_ids or item.item_id in self._items_by_id:
                raise ValueError(f"InvestigationItem déjà existant : {item.item_id}")
            if item.subject_ref in subjects or item.subject_ref in self._item_id_by_subject:
                raise ValueError("Un InvestigationItem existe déjà pour ce sujet.")
            item_ids.add(item.item_id)
            subjects.add(item.subject_ref)
        self._repository.create_items_batch(items)
        for item in items:
            self._index_item(item)
        return items

    def update_item(self, item: InvestigationItem) -> InvestigationItem:
        self._require_open()
        current = self._items_by_id.get(item.item_id)
        if current is None:
            raise KeyError(f"InvestigationItem introuvable : {item.item_id}")
        if item.subject_ref != current.subject_ref:
            raise ValueError("La référence du sujet d'un InvestigationItem est immuable.")
        if item.updated_at < current.updated_at:
            raise ValueError("La date de mise à jour d'un InvestigationItem ne peut pas régresser.")
        self._repository.update_item(item)
        self._items_by_id[item.item_id] = item
        return item

    def delete_item(self, item_id: InvestigationItemId) -> None:
        self._require_open()
        item = self._items_by_id.get(item_id)
        if item is None:
            raise KeyError(f"InvestigationItem introuvable : {item_id}")
        self._repository.delete_item(item_id)
        del self._items_by_id[item_id]
        del self._item_id_by_subject[item.subject_ref]

    def get_item(self, item_id: InvestigationItemId) -> InvestigationItem | None:
        self._require_open()
        return self._items_by_id.get(item_id)

    def find_item_by_subject(self, subject_kind: str, subject_id: str) -> InvestigationItem | None:
        self._require_open()
        item_id = self._item_id_by_subject.get((subject_kind, subject_id))
        return self._items_by_id.get(item_id) if item_id is not None else None

    def list_items(self) -> tuple[InvestigationItem, ...]:
        self._require_open()
        return tuple(self._items_by_id.values())

    def rebuild_indexes(self) -> None:
        """Reconstruit les index dérivés à partir des seules données primaires."""
        items = self._repository.list_items()
        by_id: dict[InvestigationItemId, InvestigationItem] = {}
        by_subject: dict[tuple[str, str], InvestigationItemId] = {}
        for item in items:
            if item.item_id in by_id or item.subject_ref in by_subject:
                raise ValueError("Données Investigation incohérentes : identifiant ou sujet dupliqué.")
            by_id[item.item_id] = item
            by_subject[item.subject_ref] = item.item_id
        self._items_by_id = by_id
        self._item_id_by_subject = by_subject
        self._rebuild_collection_indexes()
        self._rebuild_hypothesis_indexes()
        self._rebuild_journal_indexes()
        self._rebuild_relation_indexes()
        self._rebuild_note_indexes()
        self._rebuild_tag_indexes()
        self._rebuild_case_indexes()

    def _index_item(self, item: InvestigationItem) -> None:
        self._items_by_id[item.item_id] = item
        self._item_id_by_subject[item.subject_ref] = item.item_id

    def create_collection(self, collection: InvestigationCollection) -> InvestigationCollection:
        self._require_open()
        if collection.collection_id in self._collections_by_id:
            raise ValueError(f"InvestigationCollection déjà existante : {collection.collection_id}")
        self._repository.create_collection(collection)
        self._index_collection(collection)
        return collection

    def update_collection(self, collection: InvestigationCollection) -> InvestigationCollection:
        self._require_open()
        current = self._collections_by_id.get(collection.collection_id)
        if current is None:
            raise KeyError(f"InvestigationCollection introuvable : {collection.collection_id}")
        if collection.updated_at < current.updated_at:
            raise ValueError("La date de mise à jour d'une Collection ne peut pas régresser.")
        self._repository.update_collection(collection)
        self._collections_by_id[collection.collection_id] = collection
        return collection

    def delete_collection(self, collection_id: InvestigationCollectionId) -> None:
        self._require_open()
        collection = self._collections_by_id.get(collection_id)
        if collection is None:
            raise KeyError(f"InvestigationCollection introuvable : {collection_id}")
        memberships = tuple(
            self._collection_memberships_by_id[self._collection_membership_id_by_pair[collection_id, target]]
            for target in self._targets_by_collection.get(collection_id, set())
        )
        for membership in memberships:
            self._repository.delete_collection_membership(membership.membership_id)
        self._repository.delete_collection(collection_id)
        for membership in memberships:
            self._unindex_collection_membership(membership)
        del self._collections_by_id[collection_id]

    def get_collection(self, collection_id: InvestigationCollectionId) -> InvestigationCollection | None:
        self._require_open()
        return self._collections_by_id.get(collection_id)

    def list_collections(self) -> tuple[InvestigationCollection, ...]:
        self._require_open()
        return tuple(self._collections_by_id.values())

    def add_to_collection(self, membership: CollectionMembership) -> CollectionMembership:
        self._require_open()
        if membership.membership_id in self._collection_memberships_by_id:
            raise ValueError(f"CollectionMembership déjà existant : {membership.membership_id}")
        if membership.collection_id not in self._collections_by_id:
            raise KeyError(f"InvestigationCollection introuvable : {membership.collection_id}")
        pair = membership.collection_id, membership.target_ref
        if pair in self._collection_membership_id_by_pair:
            raise ValueError("Cette cible appartient déjà à cette Collection.")
        self._repository.create_collection_membership(membership)
        self._index_collection_membership(membership)
        return membership

    def add_to_collection_batch(
        self, memberships: tuple[CollectionMembership, ...]
    ) -> tuple[CollectionMembership, ...]:
        """Ajoute des memberships validés en une seule écriture logique."""
        self._require_open()
        pairs: set[tuple[InvestigationCollectionId, InvestigationTargetRef]] = set()
        membership_ids: set[CollectionMembershipId] = set()
        for membership in memberships:
            if (
                membership.membership_id in membership_ids
                or membership.membership_id in self._collection_memberships_by_id
            ):
                raise ValueError(f"CollectionMembership déjà existant : {membership.membership_id}")
            if membership.collection_id not in self._collections_by_id:
                raise KeyError(f"InvestigationCollection introuvable : {membership.collection_id}")
            pair = membership.collection_id, membership.target_ref
            if pair in pairs or pair in self._collection_membership_id_by_pair:
                raise ValueError("Cette cible appartient déjà à cette Collection.")
            pairs.add(pair)
            membership_ids.add(membership.membership_id)
        self._repository.create_collection_memberships_batch(memberships)
        for membership in memberships:
            self._index_collection_membership(membership)
        return memberships

    def remove_from_collection(self, collection_id: InvestigationCollectionId, target: InvestigationTargetRef) -> None:
        self._require_open()
        membership_id = self._collection_membership_id_by_pair.get((collection_id, target))
        if membership_id is None:
            raise KeyError("Ce membership est introuvable.")
        membership = self._collection_memberships_by_id[membership_id]
        self._repository.delete_collection_membership(membership_id)
        self._unindex_collection_membership(membership)

    def find_collection_members(self, collection_id: InvestigationCollectionId) -> tuple[InvestigationTargetRef, ...]:
        self._require_open()
        if collection_id not in self._collections_by_id:
            raise KeyError(f"InvestigationCollection introuvable : {collection_id}")
        return tuple(self._targets_by_collection.get(collection_id, set()))

    def find_collections_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationCollection, ...]:
        self._require_open()
        return tuple(
            self._collections_by_id[collection_id]
            for collection_id in self._collection_ids_by_target.get(target, set())
        )

    def _rebuild_collection_indexes(self) -> None:
        self._collections_by_id = {}
        self._collection_memberships_by_id = {}
        self._collection_ids_by_target = {}
        self._targets_by_collection = {}
        self._collection_membership_id_by_pair = {}
        for collection in self._repository.list_collections():
            if collection.collection_id in self._collections_by_id:
                raise ValueError("Données Investigation incohérentes : Collection dupliquée.")
            self._index_collection(collection)
        for membership in self._repository.list_collection_memberships():
            if membership.membership_id in self._collection_memberships_by_id:
                raise ValueError("Données Investigation incohérentes : membership dupliqué.")
            if membership.collection_id not in self._collections_by_id:
                raise ValueError("Données Investigation incohérentes : membership orphelin.")
            if (membership.collection_id, membership.target_ref) in self._collection_membership_id_by_pair:
                raise ValueError("Données Investigation incohérentes : membership redondant.")
            self._index_collection_membership(membership)

    def _index_collection(self, collection: InvestigationCollection) -> None:
        self._collections_by_id[collection.collection_id] = collection

    def _index_collection_membership(self, membership: CollectionMembership) -> None:
        self._collection_memberships_by_id[membership.membership_id] = membership
        self._collection_ids_by_target.setdefault(membership.target_ref, set()).add(membership.collection_id)
        self._targets_by_collection.setdefault(membership.collection_id, set()).add(membership.target_ref)
        self._collection_membership_id_by_pair[membership.collection_id, membership.target_ref] = (
            membership.membership_id
        )

    def _unindex_collection_membership(self, membership: CollectionMembership) -> None:
        del self._collection_memberships_by_id[membership.membership_id]
        pair = membership.collection_id, membership.target_ref
        del self._collection_membership_id_by_pair[pair]
        target_collections = self._collection_ids_by_target[membership.target_ref]
        target_collections.remove(membership.collection_id)
        if not target_collections:
            del self._collection_ids_by_target[membership.target_ref]
        collection_targets = self._targets_by_collection[membership.collection_id]
        collection_targets.remove(membership.target_ref)
        if not collection_targets:
            del self._targets_by_collection[membership.collection_id]

    def create_hypothesis(self, hypothesis: InvestigationHypothesis) -> InvestigationHypothesis:
        self._require_open()
        if hypothesis.hypothesis_id in self._hypotheses_by_id:
            raise ValueError(f"InvestigationHypothesis déjà existante : {hypothesis.hypothesis_id}")
        self._repository.create_hypothesis(hypothesis)
        self._index_hypothesis(hypothesis)
        return hypothesis

    def update_hypothesis(self, hypothesis: InvestigationHypothesis) -> InvestigationHypothesis:
        self._require_open()
        current = self._hypotheses_by_id.get(hypothesis.hypothesis_id)
        if current is None:
            raise KeyError(f"InvestigationHypothesis introuvable : {hypothesis.hypothesis_id}")
        if hypothesis.updated_at < current.updated_at:
            raise ValueError("La date de mise à jour d'une Hypothèse ne peut pas régresser.")
        self._repository.update_hypothesis(hypothesis)
        self._hypotheses_by_id[hypothesis.hypothesis_id] = hypothesis
        return hypothesis

    def delete_hypothesis(self, hypothesis_id: InvestigationHypothesisId) -> None:
        self._require_open()
        hypothesis = self._hypotheses_by_id.get(hypothesis_id)
        if hypothesis is None:
            raise KeyError(f"InvestigationHypothesis introuvable : {hypothesis_id}")
        memberships = tuple(
            self._hypothesis_memberships_by_id[self._hypothesis_membership_id_by_pair[hypothesis_id, target]]
            for target in self._targets_by_hypothesis.get(hypothesis_id, set())
        )
        for membership in memberships:
            self._repository.delete_hypothesis_membership(membership.membership_id)
        self._repository.delete_hypothesis(hypothesis_id)
        for membership in memberships:
            self._unindex_hypothesis_membership(membership)
        del self._hypotheses_by_id[hypothesis_id]

    def get_hypothesis(self, hypothesis_id: InvestigationHypothesisId) -> InvestigationHypothesis | None:
        self._require_open()
        return self._hypotheses_by_id.get(hypothesis_id)

    def list_hypotheses(self) -> tuple[InvestigationHypothesis, ...]:
        self._require_open()
        return tuple(self._hypotheses_by_id.values())

    def add_to_hypothesis(self, membership: HypothesisMembership) -> HypothesisMembership:
        self._require_open()
        if membership.membership_id in self._hypothesis_memberships_by_id:
            raise ValueError(f"HypothesisMembership déjà existant : {membership.membership_id}")
        if membership.hypothesis_id not in self._hypotheses_by_id:
            raise KeyError(f"InvestigationHypothesis introuvable : {membership.hypothesis_id}")
        pair = membership.hypothesis_id, membership.target_ref
        if pair in self._hypothesis_membership_id_by_pair:
            raise ValueError("Cette cible appartient déjà à cette Hypothèse.")
        self._repository.create_hypothesis_membership(membership)
        self._index_hypothesis_membership(membership)
        return membership

    def remove_from_hypothesis(self, hypothesis_id: InvestigationHypothesisId, target: InvestigationTargetRef) -> None:
        self._require_open()
        membership_id = self._hypothesis_membership_id_by_pair.get((hypothesis_id, target))
        if membership_id is None:
            raise KeyError("Ce membership est introuvable.")
        membership = self._hypothesis_memberships_by_id[membership_id]
        self._repository.delete_hypothesis_membership(membership_id)
        self._unindex_hypothesis_membership(membership)

    def find_hypothesis_members(self, hypothesis_id: InvestigationHypothesisId) -> tuple[InvestigationTargetRef, ...]:
        self._require_open()
        if hypothesis_id not in self._hypotheses_by_id:
            raise KeyError(f"InvestigationHypothesis introuvable : {hypothesis_id}")
        return tuple(self._targets_by_hypothesis.get(hypothesis_id, set()))

    def find_hypothesis_memberships(self, hypothesis_id: InvestigationHypothesisId) -> tuple[HypothesisMembership, ...]:
        """Retourne les memberships typés afin de préserver le rôle de chaque cible."""
        self._require_open()
        if hypothesis_id not in self._hypotheses_by_id:
            raise KeyError(f"InvestigationHypothesis introuvable : {hypothesis_id}")
        return tuple(
            self._hypothesis_memberships_by_id[self._hypothesis_membership_id_by_pair[hypothesis_id, target]]
            for target in self._targets_by_hypothesis.get(hypothesis_id, set())
        )

    def find_hypotheses_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationHypothesis, ...]:
        self._require_open()
        return tuple(
            self._hypotheses_by_id[hypothesis_id] for hypothesis_id in self._hypothesis_ids_by_target.get(target, set())
        )

    def _rebuild_hypothesis_indexes(self) -> None:
        self._hypotheses_by_id = {}
        self._hypothesis_memberships_by_id = {}
        self._hypothesis_ids_by_target = {}
        self._targets_by_hypothesis = {}
        self._hypothesis_membership_ids_by_role = {}
        self._hypothesis_membership_id_by_pair = {}
        for hypothesis in self._repository.list_hypotheses():
            if hypothesis.hypothesis_id in self._hypotheses_by_id:
                raise ValueError("Données Investigation incohérentes : Hypothèse dupliquée.")
            self._index_hypothesis(hypothesis)
        for membership in self._repository.list_hypothesis_memberships():
            if membership.membership_id in self._hypothesis_memberships_by_id:
                raise ValueError("Données Investigation incohérentes : membership dupliqué.")
            if membership.hypothesis_id not in self._hypotheses_by_id:
                raise ValueError("Données Investigation incohérentes : membership orphelin.")
            if (membership.hypothesis_id, membership.target_ref) in self._hypothesis_membership_id_by_pair:
                raise ValueError("Données Investigation incohérentes : membership redondant.")
            self._index_hypothesis_membership(membership)

    def _index_hypothesis(self, hypothesis: InvestigationHypothesis) -> None:
        self._hypotheses_by_id[hypothesis.hypothesis_id] = hypothesis

    def _index_hypothesis_membership(self, membership: HypothesisMembership) -> None:
        self._hypothesis_memberships_by_id[membership.membership_id] = membership
        self._hypothesis_ids_by_target.setdefault(membership.target_ref, set()).add(membership.hypothesis_id)
        self._targets_by_hypothesis.setdefault(membership.hypothesis_id, set()).add(membership.target_ref)
        self._hypothesis_membership_ids_by_role.setdefault(membership.role, set()).add(membership.membership_id)
        self._hypothesis_membership_id_by_pair[membership.hypothesis_id, membership.target_ref] = (
            membership.membership_id
        )

    def _unindex_hypothesis_membership(self, membership: HypothesisMembership) -> None:
        del self._hypothesis_memberships_by_id[membership.membership_id]
        pair = membership.hypothesis_id, membership.target_ref
        del self._hypothesis_membership_id_by_pair[pair]
        target_hypotheses = self._hypothesis_ids_by_target[membership.target_ref]
        target_hypotheses.remove(membership.hypothesis_id)
        if not target_hypotheses:
            del self._hypothesis_ids_by_target[membership.target_ref]
        hypothesis_targets = self._targets_by_hypothesis[membership.hypothesis_id]
        hypothesis_targets.remove(membership.target_ref)
        if not hypothesis_targets:
            del self._targets_by_hypothesis[membership.hypothesis_id]
        role_memberships = self._hypothesis_membership_ids_by_role[membership.role]
        role_memberships.remove(membership.membership_id)
        if not role_memberships:
            del self._hypothesis_membership_ids_by_role[membership.role]

    def _append_journal_entry(self, entry: InvestigationJournalEntry) -> InvestigationJournalEntry:
        """Point d'écriture interne append-only réservé à JournalSubscriber."""
        self._require_open()
        if entry.entry_id in self._journal_entries_by_id:
            raise ValueError(f"InvestigationJournalEntry déjà existante : {entry.entry_id}")
        self._repository.append_journal_entry(entry)
        self._index_journal_entry(entry)
        return entry

    def list_journal_entries(self) -> tuple[InvestigationJournalEntry, ...]:
        self._require_open()
        return tuple(sorted(self._journal_entries_by_id.values(), key=lambda entry: (entry.timestamp, entry.entry_id)))

    def find_journal_entries_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationJournalEntry, ...]:
        self._require_open()
        return self._journal_entries_from_ids(self._journal_entry_ids_by_target.get(target, set()))

    def find_journal_entries_by_event_type(self, event_type: EventType) -> tuple[InvestigationJournalEntry, ...]:
        self._require_open()
        if not isinstance(event_type, EventType):
            raise ValueError("Le type d'événement du Journal doit être typé.")
        return self._journal_entries_from_ids(self._journal_entry_ids_by_event_type.get(event_type, set()))

    def find_journal_entries_between_dates(
        self, start: datetime, end: datetime
    ) -> tuple[InvestigationJournalEntry, ...]:
        self._require_open()
        if (
            not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is None
            or end.tzinfo is None
            or end < start
        ):
            raise ValueError("La période du Journal doit être ordonnée et inclure un fuseau horaire.")
        identifiers = {
            entry_id
            for timestamp, entry_ids in self._journal_entry_ids_by_timestamp.items()
            if start <= timestamp <= end
            for entry_id in entry_ids
        }
        return self._journal_entries_from_ids(identifiers)

    def _rebuild_journal_indexes(self) -> None:
        self._journal_entries_by_id = {}
        self._journal_entry_ids_by_timestamp = {}
        self._journal_entry_ids_by_event_type = {}
        self._journal_entry_ids_by_target = {}
        for entry in self._repository.list_journal_entries():
            if entry.entry_id in self._journal_entries_by_id:
                raise ValueError("Données Investigation incohérentes : entrée de Journal dupliquée.")
            self._index_journal_entry(entry)

    def _index_journal_entry(self, entry: InvestigationJournalEntry) -> None:
        self._journal_entries_by_id[entry.entry_id] = entry
        self._journal_entry_ids_by_timestamp.setdefault(entry.timestamp, set()).add(entry.entry_id)
        self._journal_entry_ids_by_event_type.setdefault(entry.event_type, set()).add(entry.entry_id)
        if entry.target_ref is not None:
            self._journal_entry_ids_by_target.setdefault(entry.target_ref, set()).add(entry.entry_id)

    def _journal_entries_from_ids(
        self, identifiers: set[InvestigationJournalEntryId]
    ) -> tuple[InvestigationJournalEntry, ...]:
        return tuple(
            sorted(
                (self._journal_entries_by_id[entry_id] for entry_id in identifiers),
                key=lambda entry: (entry.timestamp, entry.entry_id),
            )
        )

    def create_relation(self, relation: InvestigationRelation) -> InvestigationRelation:
        self._require_open()
        normalized = self._normalize_relation(relation)
        if normalized.relation_id in self._relations_by_id:
            raise ValueError(f"InvestigationRelation déjà existante : {normalized.relation_id}")
        self._validate_relation(normalized)
        self._repository.create_relation(normalized)
        self._index_relation(normalized)
        return normalized

    def update_relation(self, relation: InvestigationRelation) -> InvestigationRelation:
        self._require_open()
        current = self._relations_by_id.get(relation.relation_id)
        if current is None:
            raise KeyError(f"InvestigationRelation introuvable : {relation.relation_id}")
        if relation.updated_at < current.updated_at:
            raise ValueError("La date de mise à jour d'une relation ne peut pas régresser.")
        normalized = self._normalize_relation(relation)
        self._validate_relation(normalized)
        self._repository.update_relation(normalized)
        self._unindex_relation(current)
        self._index_relation(normalized)
        return normalized

    def delete_relation(self, relation_id: InvestigationRelationId) -> None:
        self._require_open()
        relation = self._relations_by_id.get(relation_id)
        if relation is None:
            raise KeyError(f"InvestigationRelation introuvable : {relation_id}")
        self._repository.delete_relation(relation_id)
        self._unindex_relation(relation)

    def get_relation(self, relation_id: InvestigationRelationId) -> InvestigationRelation | None:
        self._require_open()
        return self._relations_by_id.get(relation_id)

    def list_relations(self) -> tuple[InvestigationRelation, ...]:
        self._require_open()
        return tuple(self._relations_by_id.values())

    def find_relations_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationRelation, ...]:
        self._require_open()
        relation_ids = self._relation_ids_by_source.get(target, set()) | self._relation_ids_by_destination.get(
            target, set()
        )
        return tuple(self._relations_by_id[relation_id] for relation_id in relation_ids)

    def _rebuild_relation_indexes(self) -> None:
        self._relations_by_id = {}
        self._relation_ids_by_source = {}
        self._relation_ids_by_destination = {}
        self._relation_ids_by_type = {}
        self._relation_id_by_signature = {}
        for relation in self._repository.list_relations():
            normalized = self._normalize_relation(relation)
            if normalized != relation:
                raise ValueError("Données Investigation incohérentes : relation symétrique non normalisée.")
            if relation.relation_id in self._relations_by_id:
                raise ValueError("Données Investigation incohérentes : identifiant de relation dupliqué.")
            self._validate_relation(relation)
            self._index_relation(relation)

    def _validate_relation(self, relation: InvestigationRelation) -> None:
        if relation.source_target == relation.destination_target and not relation.semantics.allows_self_reference:
            raise ValueError("Une relation ne peut pas référencer la même cible deux fois.")
        duplicate = self._relation_id_by_signature.get(relation.signature)
        if duplicate is not None and duplicate != relation.relation_id:
            raise ValueError("Une relation identique existe déjà.")

    @staticmethod
    def _normalize_relation(relation: InvestigationRelation) -> InvestigationRelation:
        if relation.semantics.symmetric and relation.destination_target.sort_key < relation.source_target.sort_key:
            from dataclasses import replace

            return replace(
                relation,
                source_target=relation.destination_target,
                destination_target=relation.source_target,
            )
        return relation

    def _index_relation(self, relation: InvestigationRelation) -> None:
        self._relations_by_id[relation.relation_id] = relation
        self._relation_ids_by_source.setdefault(relation.source_target, set()).add(relation.relation_id)
        self._relation_ids_by_destination.setdefault(relation.destination_target, set()).add(relation.relation_id)
        self._relation_ids_by_type.setdefault(relation.relation_type, set()).add(relation.relation_id)
        self._relation_id_by_signature[relation.signature] = relation.relation_id

    def _unindex_relation(self, relation: InvestigationRelation) -> None:
        del self._relations_by_id[relation.relation_id]
        for index, key in (
            (self._relation_ids_by_source, relation.source_target),
            (self._relation_ids_by_destination, relation.destination_target),
            (self._relation_ids_by_type, relation.relation_type),
        ):
            identifiers = index[key]
            identifiers.remove(relation.relation_id)
            if not identifiers:
                del index[key]
        del self._relation_id_by_signature[relation.signature]

    def create_note(self, note: InvestigationNote) -> InvestigationNote:
        self._require_open()
        if note.note_id in self._notes_by_id:
            raise ValueError(f"InvestigationNote déjà existante : {note.note_id}")
        self._repository.create_note(note)
        self._index_note(note)
        return note

    def update_note(self, note: InvestigationNote) -> InvestigationNote:
        self._require_open()
        current = self._notes_by_id.get(note.note_id)
        if current is None:
            raise KeyError(f"InvestigationNote introuvable : {note.note_id}")
        if note.updated_at < current.updated_at:
            raise ValueError("La date de mise à jour d'une note ne peut pas régresser.")
        self._repository.update_note(note)
        self._unindex_note(current)
        self._index_note(note)
        return note

    def delete_note(self, note_id: InvestigationNoteId) -> None:
        self._require_open()
        note = self._notes_by_id.get(note_id)
        if note is None:
            raise KeyError(f"InvestigationNote introuvable : {note_id}")
        self._repository.delete_note(note_id)
        self._unindex_note(note)

    def get_note(self, note_id: InvestigationNoteId) -> InvestigationNote | None:
        self._require_open()
        return self._notes_by_id.get(note_id)

    def list_notes(self) -> tuple[InvestigationNote, ...]:
        self._require_open()
        return tuple(self._notes_by_id.values())

    def find_notes_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationNote, ...]:
        self._require_open()
        return tuple(self._notes_by_id[note_id] for note_id in self._note_ids_by_target.get(target, set()))

    def _rebuild_note_indexes(self) -> None:
        self._notes_by_id = {}
        self._note_ids_by_target = {}
        self._note_ids_by_author = {}
        for note in self._repository.list_notes():
            if note.note_id in self._notes_by_id:
                raise ValueError("Données Investigation incohérentes : identifiant de note dupliqué.")
            self._index_note(note)

    def _index_note(self, note: InvestigationNote) -> None:
        self._notes_by_id[note.note_id] = note
        if note.target_ref is not None:
            self._note_ids_by_target.setdefault(note.target_ref, set()).add(note.note_id)
        self._note_ids_by_author.setdefault(note.author, set()).add(note.note_id)

    def _unindex_note(self, note: InvestigationNote) -> None:
        del self._notes_by_id[note.note_id]
        if note.target_ref is not None:
            target_ids = self._note_ids_by_target[note.target_ref]
            target_ids.remove(note.note_id)
            if not target_ids:
                del self._note_ids_by_target[note.target_ref]
        author_ids = self._note_ids_by_author[note.author]
        author_ids.remove(note.note_id)
        if not author_ids:
            del self._note_ids_by_author[note.author]

    def create_tag(self, tag: InvestigationTag) -> InvestigationTag:
        self._require_open()
        if tag.tag_id in self._tags_by_id:
            raise ValueError(f"InvestigationTag déjà existant : {tag.tag_id}")
        if tag.normalized_name in self._tag_id_by_normalized_name:
            raise ValueError("Un tag possède déjà ce nom normalisé.")
        self._repository.create_tag(tag)
        self._index_tag(tag)
        return tag

    def update_tag(self, tag: InvestigationTag) -> InvestigationTag:
        self._require_open()
        current = self._tags_by_id.get(tag.tag_id)
        if current is None:
            raise KeyError(f"InvestigationTag introuvable : {tag.tag_id}")
        if tag.updated_at < current.updated_at:
            raise ValueError("La date de mise à jour d'un tag ne peut pas régresser.")
        duplicate = self._tag_id_by_normalized_name.get(tag.normalized_name)
        if duplicate is not None and duplicate != tag.tag_id:
            raise ValueError("Un tag possède déjà ce nom normalisé.")
        self._repository.update_tag(tag)
        self._unindex_tag(current)
        self._index_tag(tag)
        return tag

    def delete_tag(self, tag_id: InvestigationTagId) -> None:
        self._require_open()
        tag = self._tags_by_id.get(tag_id)
        if tag is None:
            raise KeyError(f"InvestigationTag introuvable : {tag_id}")
        assignments = tuple(
            self._assignments_by_id[self._assignment_id_by_pair[tag_id, target]]
            for target in self._targets_by_tag.get(tag_id, set())
        )
        for assignment in assignments:
            self._repository.delete_tag_assignment(assignment.assignment_id)
        self._repository.delete_tag(tag_id)
        for assignment in assignments:
            self._unindex_assignment(assignment)
        self._unindex_tag(tag)

    def get_tag(self, tag_id: InvestigationTagId) -> InvestigationTag | None:
        self._require_open()
        return self._tags_by_id.get(tag_id)

    def list_tags(self) -> tuple[InvestigationTag, ...]:
        self._require_open()
        return tuple(self._tags_by_id.values())

    def assign_tag(self, assignment: TagAssignment) -> TagAssignment:
        self._require_open()
        if assignment.assignment_id in self._assignments_by_id:
            raise ValueError(f"TagAssignment déjà existante : {assignment.assignment_id}")
        if assignment.tag_id not in self._tags_by_id:
            raise KeyError(f"InvestigationTag introuvable : {assignment.tag_id}")
        pair = assignment.tag_id, assignment.target_ref
        if pair in self._assignment_id_by_pair:
            raise ValueError("Ce tag est déjà assigné à cette cible.")
        self._repository.create_tag_assignment(assignment)
        self._index_assignment(assignment)
        return assignment

    def unassign_tag(self, tag_id: InvestigationTagId, target: InvestigationTargetRef) -> None:
        self._require_open()
        assignment_id = self._assignment_id_by_pair.get((tag_id, target))
        if assignment_id is None:
            raise KeyError("Cette assignation de tag est introuvable.")
        assignment = self._assignments_by_id[assignment_id]
        self._repository.delete_tag_assignment(assignment_id)
        self._unindex_assignment(assignment)

    def find_tags_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationTag, ...]:
        self._require_open()
        return tuple(self._tags_by_id[tag_id] for tag_id in self._tag_ids_by_target.get(target, set()))

    def find_targets_for_tag(self, tag_id: InvestigationTagId) -> tuple[InvestigationTargetRef, ...]:
        self._require_open()
        if tag_id not in self._tags_by_id:
            raise KeyError(f"InvestigationTag introuvable : {tag_id}")
        return tuple(self._targets_by_tag.get(tag_id, set()))

    def tag_usage_count(self, tag_id: InvestigationTagId) -> int:
        self._require_open()
        if tag_id not in self._tags_by_id:
            raise KeyError(f"InvestigationTag introuvable : {tag_id}")
        return len(self._targets_by_tag.get(tag_id, set()))

    def _rebuild_tag_indexes(self) -> None:
        self._tags_by_id = {}
        self._tag_id_by_normalized_name = {}
        self._assignments_by_id = {}
        self._tag_ids_by_target = {}
        self._targets_by_tag = {}
        self._assignment_id_by_pair = {}
        for tag in self._repository.list_tags():
            if tag.tag_id in self._tags_by_id or tag.normalized_name in self._tag_id_by_normalized_name:
                raise ValueError("Données Investigation incohérentes : tag dupliqué.")
            self._index_tag(tag)
        for assignment in self._repository.list_tag_assignments():
            if assignment.assignment_id in self._assignments_by_id:
                raise ValueError("Données Investigation incohérentes : assignation dupliquée.")
            if assignment.tag_id not in self._tags_by_id:
                raise ValueError("Données Investigation incohérentes : assignation orpheline.")
            if (assignment.tag_id, assignment.target_ref) in self._assignment_id_by_pair:
                raise ValueError("Données Investigation incohérentes : assignation redondante.")
            self._index_assignment(assignment)

    def _index_tag(self, tag: InvestigationTag) -> None:
        self._tags_by_id[tag.tag_id] = tag
        self._tag_id_by_normalized_name[tag.normalized_name] = tag.tag_id

    def _unindex_tag(self, tag: InvestigationTag) -> None:
        del self._tags_by_id[tag.tag_id]
        del self._tag_id_by_normalized_name[tag.normalized_name]

    def _index_assignment(self, assignment: TagAssignment) -> None:
        self._assignments_by_id[assignment.assignment_id] = assignment
        self._tag_ids_by_target.setdefault(assignment.target_ref, set()).add(assignment.tag_id)
        self._targets_by_tag.setdefault(assignment.tag_id, set()).add(assignment.target_ref)
        self._assignment_id_by_pair[assignment.tag_id, assignment.target_ref] = assignment.assignment_id

    def _unindex_assignment(self, assignment: TagAssignment) -> None:
        del self._assignments_by_id[assignment.assignment_id]
        pair = assignment.tag_id, assignment.target_ref
        del self._assignment_id_by_pair[pair]
        target_tags = self._tag_ids_by_target[assignment.target_ref]
        target_tags.remove(assignment.tag_id)
        if not target_tags:
            del self._tag_ids_by_target[assignment.target_ref]
        tag_targets = self._targets_by_tag[assignment.tag_id]
        tag_targets.remove(assignment.target_ref)
        if not tag_targets:
            del self._targets_by_tag[assignment.tag_id]

    def create_case(self, case: InvestigationCase) -> InvestigationCase:
        self._require_open()
        if case.case_id in self._cases_by_id:
            raise ValueError(f"InvestigationCase déjà existante : {case.case_id}")
        self._repository.create_case(case)
        self._index_case(case)
        return case

    def update_case(self, case: InvestigationCase) -> InvestigationCase:
        self._require_open()
        current = self._cases_by_id.get(case.case_id)
        if current is None:
            raise KeyError(f"InvestigationCase introuvable : {case.case_id}")
        if case.updated_at < current.updated_at:
            raise ValueError("La date de mise à jour d'une Case ne peut pas régresser.")
        self._repository.update_case(case)
        self._cases_by_id[case.case_id] = case
        return case

    def delete_case(self, case_id: InvestigationCaseId) -> None:
        self._require_open()
        case = self._cases_by_id.get(case_id)
        if case is None:
            raise KeyError(f"InvestigationCase introuvable : {case_id}")
        memberships = tuple(
            self._case_memberships_by_id[self._case_membership_id_by_pair[case_id, target]]
            for target in self._targets_by_case.get(case_id, set())
        )
        for membership in memberships:
            self._repository.delete_case_membership(membership.membership_id)
        self._repository.delete_case(case_id)
        for membership in memberships:
            self._unindex_case_membership(membership)
        del self._cases_by_id[case_id]

    def get_case(self, case_id: InvestigationCaseId) -> InvestigationCase | None:
        self._require_open()
        return self._cases_by_id.get(case_id)

    def list_cases(self) -> tuple[InvestigationCase, ...]:
        self._require_open()
        return tuple(self._cases_by_id.values())

    def add_to_case(self, membership: CaseMembership) -> CaseMembership:
        self._require_open()
        if membership.membership_id in self._case_memberships_by_id:
            raise ValueError(f"CaseMembership déjà existant : {membership.membership_id}")
        if membership.case_id not in self._cases_by_id:
            raise KeyError(f"InvestigationCase introuvable : {membership.case_id}")
        pair = membership.case_id, membership.target_ref
        if pair in self._case_membership_id_by_pair:
            raise ValueError("Cette cible appartient déjà à cette Case.")
        self._repository.create_case_membership(membership)
        self._index_case_membership(membership)
        return membership

    def add_to_case_batch(self, memberships: tuple[CaseMembership, ...]) -> tuple[CaseMembership, ...]:
        """Ajoute des memberships Case validés en une seule écriture logique."""
        self._require_open()
        pairs: set[tuple[InvestigationCaseId, InvestigationTargetRef]] = set()
        membership_ids: set[CaseMembershipId] = set()
        for membership in memberships:
            if membership.membership_id in membership_ids or membership.membership_id in self._case_memberships_by_id:
                raise ValueError(f"CaseMembership déjà existant : {membership.membership_id}")
            if membership.case_id not in self._cases_by_id:
                raise KeyError(f"InvestigationCase introuvable : {membership.case_id}")
            pair = membership.case_id, membership.target_ref
            if pair in pairs or pair in self._case_membership_id_by_pair:
                raise ValueError("Cette cible appartient déjà à cette Case.")
            pairs.add(pair)
            membership_ids.add(membership.membership_id)
        self._repository.create_case_memberships_batch(memberships)
        for membership in memberships:
            self._index_case_membership(membership)
        return memberships

    def remove_from_case(self, case_id: InvestigationCaseId, target: InvestigationTargetRef) -> None:
        self._require_open()
        membership_id = self._case_membership_id_by_pair.get((case_id, target))
        if membership_id is None:
            raise KeyError("Ce membership est introuvable.")
        membership = self._case_memberships_by_id[membership_id]
        self._repository.delete_case_membership(membership_id)
        self._unindex_case_membership(membership)

    def find_case_members(self, case_id: InvestigationCaseId) -> tuple[InvestigationTargetRef, ...]:
        self._require_open()
        if case_id not in self._cases_by_id:
            raise KeyError(f"InvestigationCase introuvable : {case_id}")
        return tuple(self._targets_by_case.get(case_id, set()))

    def find_cases_for_target(self, target: InvestigationTargetRef) -> tuple[InvestigationCase, ...]:
        self._require_open()
        return tuple(self._cases_by_id[case_id] for case_id in self._case_ids_by_target.get(target, set()))

    def _rebuild_case_indexes(self) -> None:
        self._cases_by_id = {}
        self._case_memberships_by_id = {}
        self._case_ids_by_target = {}
        self._targets_by_case = {}
        self._case_membership_id_by_pair = {}
        for case in self._repository.list_cases():
            if case.case_id in self._cases_by_id:
                raise ValueError("Données Investigation incohérentes : Case dupliquée.")
            self._index_case(case)
        for membership in self._repository.list_case_memberships():
            if membership.membership_id in self._case_memberships_by_id:
                raise ValueError("Données Investigation incohérentes : membership dupliqué.")
            if membership.case_id not in self._cases_by_id:
                raise ValueError("Données Investigation incohérentes : membership orphelin.")
            if (membership.case_id, membership.target_ref) in self._case_membership_id_by_pair:
                raise ValueError("Données Investigation incohérentes : membership redondant.")
            self._index_case_membership(membership)

    def _index_case(self, case: InvestigationCase) -> None:
        self._cases_by_id[case.case_id] = case

    def _index_case_membership(self, membership: CaseMembership) -> None:
        self._case_memberships_by_id[membership.membership_id] = membership
        self._case_ids_by_target.setdefault(membership.target_ref, set()).add(membership.case_id)
        self._targets_by_case.setdefault(membership.case_id, set()).add(membership.target_ref)
        self._case_membership_id_by_pair[membership.case_id, membership.target_ref] = membership.membership_id

    def _unindex_case_membership(self, membership: CaseMembership) -> None:
        del self._case_memberships_by_id[membership.membership_id]
        pair = membership.case_id, membership.target_ref
        del self._case_membership_id_by_pair[pair]
        target_cases = self._case_ids_by_target[membership.target_ref]
        target_cases.remove(membership.case_id)
        if not target_cases:
            del self._case_ids_by_target[membership.target_ref]
        case_targets = self._targets_by_case[membership.case_id]
        case_targets.remove(membership.target_ref)
        if not case_targets:
            del self._targets_by_case[membership.case_id]

    def _require_open(self) -> None:
        if not self._is_open:
            raise RuntimeError("Le module Investigation n'est pas ouvert.")
