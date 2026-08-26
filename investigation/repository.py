"""Accès logique réservé aux futurs agrégats du module Investigation."""

from __future__ import annotations

from collections.abc import Mapping

from investigation.case import CaseMembership, CaseMembershipId, InvestigationCase, InvestigationCaseId
from investigation.collection import (
    CollectionMembership,
    CollectionMembershipId,
    InvestigationCollection,
    InvestigationCollectionId,
)
from investigation.hypothesis import (
    HypothesisMembership,
    HypothesisMembershipId,
    InvestigationHypothesis,
    InvestigationHypothesisId,
)
from investigation.item import InvestigationItem, InvestigationItemId
from investigation.journal import InvestigationJournalEntry, InvestigationJournalEntryId
from investigation.note import InvestigationNote, InvestigationNoteId
from investigation.relation import InvestigationRelation, InvestigationRelationId
from investigation.tag import InvestigationTag, InvestigationTagId, TagAssignment, TagAssignmentId
from project.stores import ProjectStore


class InvestigationRepository:
    """Expose les stores déclarés sans connaître leur support physique.

    Cette première phase ne persiste aucune entité d'enquête. Les noms sont
    néanmoins réservés dans le contrat du module afin que les phases suivantes
    n'aient pas à modifier son intégration au système de projets.
    """

    MODULE_ID = "investigation"
    STORE_NAMES = frozenset(
        {
            "items",
            "collections",
            "collection_memberships",
            "notes",
            "tags",
            "tag_assignments",
            "relations",
            "hypotheses",
            "hypothesis_memberships",
            "cases",
            "case_memberships",
            "journal",
        }
    )
    ITEMS_STORE = "items"
    COLLECTIONS_STORE = "collections"
    COLLECTION_MEMBERSHIPS_STORE = "collection_memberships"
    HYPOTHESES_STORE = "hypotheses"
    HYPOTHESIS_MEMBERSHIPS_STORE = "hypothesis_memberships"
    JOURNAL_STORE = "journal"
    RELATIONS_STORE = "relations"
    NOTES_STORE = "notes"
    TAGS_STORE = "tags"
    TAG_ASSIGNMENTS_STORE = "tag_assignments"
    CASES_STORE = "cases"
    CASE_MEMBERSHIPS_STORE = "case_memberships"

    def __init__(self, stores: Mapping[str, ProjectStore]) -> None:
        unknown_stores = frozenset(stores) - self.STORE_NAMES
        if unknown_stores:
            raise ValueError("Les stores du module Investigation sont inconnus.")
        self._stores = dict(stores)

    @property
    def _items(self) -> ProjectStore:
        return self._required_store(self.ITEMS_STORE)

    @property
    def _collections(self) -> ProjectStore:
        return self._required_store(self.COLLECTIONS_STORE)

    @property
    def _collection_memberships(self) -> ProjectStore:
        return self._required_store(self.COLLECTION_MEMBERSHIPS_STORE)

    @property
    def _hypotheses(self) -> ProjectStore:
        return self._required_store(self.HYPOTHESES_STORE)

    @property
    def _hypothesis_memberships(self) -> ProjectStore:
        return self._required_store(self.HYPOTHESIS_MEMBERSHIPS_STORE)

    @property
    def _journal(self) -> ProjectStore:
        return self._required_store(self.JOURNAL_STORE)

    @property
    def _relations(self) -> ProjectStore:
        return self._required_store(self.RELATIONS_STORE)

    @property
    def _notes(self) -> ProjectStore:
        return self._required_store(self.NOTES_STORE)

    @property
    def _tags(self) -> ProjectStore:
        return self._required_store(self.TAGS_STORE)

    @property
    def _tag_assignments(self) -> ProjectStore:
        return self._required_store(self.TAG_ASSIGNMENTS_STORE)

    @property
    def _cases(self) -> ProjectStore:
        return self._required_store(self.CASES_STORE)

    @property
    def _case_memberships(self) -> ProjectStore:
        return self._required_store(self.CASE_MEMBERSHIPS_STORE)

    @property
    def store_names(self) -> frozenset[str]:
        """Noms déclarés : utile aux migrations et aux tests d'intégration."""
        return self.STORE_NAMES

    def store(self, name: str) -> ProjectStore:
        """Retourne un store déclaré ; les services futurs restent encapsulés ici."""
        if name not in self.STORE_NAMES:
            raise KeyError(f"Store Investigation inconnu : {name}")
        return self._required_store(name)

    def _required_store(self, name: str) -> ProjectStore:
        """Évite toute fuite de KeyError depuis le backend de persistance."""
        store = self._stores.get(name)
        if store is None:
            raise RuntimeError(f"Store Investigation non initialisé : {name}")
        return store

    def create_item(self, item: InvestigationItem) -> None:
        if self.get_item(item.item_id) is not None:
            raise ValueError(f"InvestigationItem déjà existant : {item.item_id}")
        self._items.set(str(item.item_id), item)

    def create_items_batch(self, items: tuple[InvestigationItem, ...]) -> None:
        """Écrit les Items comme une transaction logique avec rollback mémoire.

        Les stores actuels n'exposent pas de transaction physique. Tous les
        contrôles sont donc réalisés avant l'écriture ; si une écriture échoue,
        les clés déjà créées sont supprimées avant de propager l'erreur.
        """
        self._create_many(self._items, ((str(item.item_id), item) for item in items), "InvestigationItem")

    def update_item(self, item: InvestigationItem) -> None:
        if self.get_item(item.item_id) is None:
            raise KeyError(f"InvestigationItem introuvable : {item.item_id}")
        self._items.set(str(item.item_id), item)

    def delete_item(self, item_id: InvestigationItemId) -> None:
        if self.get_item(item_id) is None:
            raise KeyError(f"InvestigationItem introuvable : {item_id}")
        self._items.delete(str(item_id))

    def get_item(self, item_id: InvestigationItemId) -> InvestigationItem | None:
        value = self._items.get(str(item_id))
        return value if isinstance(value, InvestigationItem) else None

    def list_items(self) -> tuple[InvestigationItem, ...]:
        return tuple(item for key in self._items.keys() if isinstance(item := self._items.get(key), InvestigationItem))

    def create_collection(self, collection: InvestigationCollection) -> None:
        if self.get_collection(collection.collection_id) is not None:
            raise ValueError(f"InvestigationCollection déjà existante : {collection.collection_id}")
        self._collections.set(str(collection.collection_id), collection)

    def update_collection(self, collection: InvestigationCollection) -> None:
        if self.get_collection(collection.collection_id) is None:
            raise KeyError(f"InvestigationCollection introuvable : {collection.collection_id}")
        self._collections.set(str(collection.collection_id), collection)

    def delete_collection(self, collection_id: InvestigationCollectionId) -> None:
        if self.get_collection(collection_id) is None:
            raise KeyError(f"InvestigationCollection introuvable : {collection_id}")
        self._collections.delete(str(collection_id))

    def get_collection(self, collection_id: InvestigationCollectionId) -> InvestigationCollection | None:
        value = self._collections.get(str(collection_id))
        return value if isinstance(value, InvestigationCollection) else None

    def list_collections(self) -> tuple[InvestigationCollection, ...]:
        return tuple(
            collection
            for key in self._collections.keys()
            if isinstance(collection := self._collections.get(key), InvestigationCollection)
        )

    def create_collection_membership(self, membership: CollectionMembership) -> None:
        if self.get_collection_membership(membership.membership_id) is not None:
            raise ValueError(f"CollectionMembership déjà existant : {membership.membership_id}")
        self._collection_memberships.set(str(membership.membership_id), membership)

    def create_collection_memberships_batch(self, memberships: tuple[CollectionMembership, ...]) -> None:
        self._create_many(
            self._collection_memberships,
            ((str(membership.membership_id), membership) for membership in memberships),
            "CollectionMembership",
        )

    @staticmethod
    def _create_many(store: ProjectStore, entries, label: str) -> None:
        prepared = tuple(entries)
        keys = tuple(key for key, _value in prepared)
        if len(keys) != len(set(keys)) or any(store.get(key) is not None for key in keys):
            raise ValueError(f"{label} déjà existant dans une opération de masse.")
        written: list[str] = []
        try:
            for key, value in prepared:
                store.set(key, value)
                written.append(key)
        except Exception:
            for key in reversed(written):
                store.delete(key)
            raise

    def delete_collection_membership(self, membership_id: CollectionMembershipId) -> None:
        if self.get_collection_membership(membership_id) is None:
            raise KeyError(f"CollectionMembership introuvable : {membership_id}")
        self._collection_memberships.delete(str(membership_id))

    def get_collection_membership(self, membership_id: CollectionMembershipId) -> CollectionMembership | None:
        value = self._collection_memberships.get(str(membership_id))
        return value if isinstance(value, CollectionMembership) else None

    def list_collection_memberships(self) -> tuple[CollectionMembership, ...]:
        return tuple(
            membership
            for key in self._collection_memberships.keys()
            if isinstance(membership := self._collection_memberships.get(key), CollectionMembership)
        )

    def create_hypothesis(self, hypothesis: InvestigationHypothesis) -> None:
        if self.get_hypothesis(hypothesis.hypothesis_id) is not None:
            raise ValueError(f"InvestigationHypothesis déjà existante : {hypothesis.hypothesis_id}")
        self._hypotheses.set(str(hypothesis.hypothesis_id), hypothesis)

    def update_hypothesis(self, hypothesis: InvestigationHypothesis) -> None:
        if self.get_hypothesis(hypothesis.hypothesis_id) is None:
            raise KeyError(f"InvestigationHypothesis introuvable : {hypothesis.hypothesis_id}")
        self._hypotheses.set(str(hypothesis.hypothesis_id), hypothesis)

    def delete_hypothesis(self, hypothesis_id: InvestigationHypothesisId) -> None:
        if self.get_hypothesis(hypothesis_id) is None:
            raise KeyError(f"InvestigationHypothesis introuvable : {hypothesis_id}")
        self._hypotheses.delete(str(hypothesis_id))

    def get_hypothesis(self, hypothesis_id: InvestigationHypothesisId) -> InvestigationHypothesis | None:
        value = self._hypotheses.get(str(hypothesis_id))
        return value if isinstance(value, InvestigationHypothesis) else None

    def list_hypotheses(self) -> tuple[InvestigationHypothesis, ...]:
        return tuple(
            hypothesis
            for key in self._hypotheses.keys()
            if isinstance(hypothesis := self._hypotheses.get(key), InvestigationHypothesis)
        )

    def create_hypothesis_membership(self, membership: HypothesisMembership) -> None:
        if self.get_hypothesis_membership(membership.membership_id) is not None:
            raise ValueError(f"HypothesisMembership déjà existant : {membership.membership_id}")
        self._hypothesis_memberships.set(str(membership.membership_id), membership)

    def delete_hypothesis_membership(self, membership_id: HypothesisMembershipId) -> None:
        if self.get_hypothesis_membership(membership_id) is None:
            raise KeyError(f"HypothesisMembership introuvable : {membership_id}")
        self._hypothesis_memberships.delete(str(membership_id))

    def get_hypothesis_membership(self, membership_id: HypothesisMembershipId) -> HypothesisMembership | None:
        value = self._hypothesis_memberships.get(str(membership_id))
        return value if isinstance(value, HypothesisMembership) else None

    def list_hypothesis_memberships(self) -> tuple[HypothesisMembership, ...]:
        return tuple(
            membership
            for key in self._hypothesis_memberships.keys()
            if isinstance(membership := self._hypothesis_memberships.get(key), HypothesisMembership)
        )

    def append_journal_entry(self, entry: InvestigationJournalEntry) -> None:
        if self.get_journal_entry(entry.entry_id) is not None:
            raise ValueError(f"InvestigationJournalEntry déjà existante : {entry.entry_id}")
        self._journal.set(str(entry.entry_id), entry)

    def get_journal_entry(self, entry_id: InvestigationJournalEntryId) -> InvestigationJournalEntry | None:
        value = self._journal.get(str(entry_id))
        return value if isinstance(value, InvestigationJournalEntry) else None

    def list_journal_entries(self) -> tuple[InvestigationJournalEntry, ...]:
        return tuple(
            entry
            for key in self._journal.keys()
            if isinstance(entry := self._journal.get(key), InvestigationJournalEntry)
        )

    def create_relation(self, relation: InvestigationRelation) -> None:
        if self.get_relation(relation.relation_id) is not None:
            raise ValueError(f"InvestigationRelation déjà existante : {relation.relation_id}")
        self._relations.set(str(relation.relation_id), relation)

    def update_relation(self, relation: InvestigationRelation) -> None:
        if self.get_relation(relation.relation_id) is None:
            raise KeyError(f"InvestigationRelation introuvable : {relation.relation_id}")
        self._relations.set(str(relation.relation_id), relation)

    def delete_relation(self, relation_id: InvestigationRelationId) -> None:
        if self.get_relation(relation_id) is None:
            raise KeyError(f"InvestigationRelation introuvable : {relation_id}")
        self._relations.delete(str(relation_id))

    def get_relation(self, relation_id: InvestigationRelationId) -> InvestigationRelation | None:
        value = self._relations.get(str(relation_id))
        return value if isinstance(value, InvestigationRelation) else None

    def list_relations(self) -> tuple[InvestigationRelation, ...]:
        return tuple(
            relation
            for key in self._relations.keys()
            if isinstance(relation := self._relations.get(key), InvestigationRelation)
        )

    def create_note(self, note: InvestigationNote) -> None:
        if self.get_note(note.note_id) is not None:
            raise ValueError(f"InvestigationNote déjà existante : {note.note_id}")
        self._notes.set(str(note.note_id), note)

    def update_note(self, note: InvestigationNote) -> None:
        if self.get_note(note.note_id) is None:
            raise KeyError(f"InvestigationNote introuvable : {note.note_id}")
        self._notes.set(str(note.note_id), note)

    def delete_note(self, note_id: InvestigationNoteId) -> None:
        if self.get_note(note_id) is None:
            raise KeyError(f"InvestigationNote introuvable : {note_id}")
        self._notes.delete(str(note_id))

    def get_note(self, note_id: InvestigationNoteId) -> InvestigationNote | None:
        value = self._notes.get(str(note_id))
        return value if isinstance(value, InvestigationNote) else None

    def list_notes(self) -> tuple[InvestigationNote, ...]:
        return tuple(note for key in self._notes.keys() if isinstance(note := self._notes.get(key), InvestigationNote))

    def create_tag(self, tag: InvestigationTag) -> None:
        if self.get_tag(tag.tag_id) is not None:
            raise ValueError(f"InvestigationTag déjà existant : {tag.tag_id}")
        self._tags.set(str(tag.tag_id), tag)

    def update_tag(self, tag: InvestigationTag) -> None:
        if self.get_tag(tag.tag_id) is None:
            raise KeyError(f"InvestigationTag introuvable : {tag.tag_id}")
        self._tags.set(str(tag.tag_id), tag)

    def delete_tag(self, tag_id: InvestigationTagId) -> None:
        if self.get_tag(tag_id) is None:
            raise KeyError(f"InvestigationTag introuvable : {tag_id}")
        self._tags.delete(str(tag_id))

    def get_tag(self, tag_id: InvestigationTagId) -> InvestigationTag | None:
        value = self._tags.get(str(tag_id))
        return value if isinstance(value, InvestigationTag) else None

    def list_tags(self) -> tuple[InvestigationTag, ...]:
        return tuple(tag for key in self._tags.keys() if isinstance(tag := self._tags.get(key), InvestigationTag))

    def create_tag_assignment(self, assignment: TagAssignment) -> None:
        if self.get_tag_assignment(assignment.assignment_id) is not None:
            raise ValueError(f"TagAssignment déjà existante : {assignment.assignment_id}")
        self._tag_assignments.set(str(assignment.assignment_id), assignment)

    def delete_tag_assignment(self, assignment_id: TagAssignmentId) -> None:
        if self.get_tag_assignment(assignment_id) is None:
            raise KeyError(f"TagAssignment introuvable : {assignment_id}")
        self._tag_assignments.delete(str(assignment_id))

    def get_tag_assignment(self, assignment_id: TagAssignmentId) -> TagAssignment | None:
        value = self._tag_assignments.get(str(assignment_id))
        return value if isinstance(value, TagAssignment) else None

    def list_tag_assignments(self) -> tuple[TagAssignment, ...]:
        return tuple(
            assignment
            for key in self._tag_assignments.keys()
            if isinstance(assignment := self._tag_assignments.get(key), TagAssignment)
        )

    def create_case(self, case: InvestigationCase) -> None:
        if self.get_case(case.case_id) is not None:
            raise ValueError(f"InvestigationCase déjà existante : {case.case_id}")
        self._cases.set(str(case.case_id), case)

    def update_case(self, case: InvestigationCase) -> None:
        if self.get_case(case.case_id) is None:
            raise KeyError(f"InvestigationCase introuvable : {case.case_id}")
        self._cases.set(str(case.case_id), case)

    def delete_case(self, case_id: InvestigationCaseId) -> None:
        if self.get_case(case_id) is None:
            raise KeyError(f"InvestigationCase introuvable : {case_id}")
        self._cases.delete(str(case_id))

    def get_case(self, case_id: InvestigationCaseId) -> InvestigationCase | None:
        value = self._cases.get(str(case_id))
        return value if isinstance(value, InvestigationCase) else None

    def list_cases(self) -> tuple[InvestigationCase, ...]:
        return tuple(case for key in self._cases.keys() if isinstance(case := self._cases.get(key), InvestigationCase))

    def create_case_membership(self, membership: CaseMembership) -> None:
        if self.get_case_membership(membership.membership_id) is not None:
            raise ValueError(f"CaseMembership déjà existant : {membership.membership_id}")
        self._case_memberships.set(str(membership.membership_id), membership)

    def delete_case_membership(self, membership_id: CaseMembershipId) -> None:
        if self.get_case_membership(membership_id) is None:
            raise KeyError(f"CaseMembership introuvable : {membership_id}")
        self._case_memberships.delete(str(membership_id))

    def get_case_membership(self, membership_id: CaseMembershipId) -> CaseMembership | None:
        value = self._case_memberships.get(str(membership_id))
        return value if isinstance(value, CaseMembership) else None

    def list_case_memberships(self) -> tuple[CaseMembership, ...]:
        return tuple(
            membership
            for key in self._case_memberships.keys()
            if isinstance(membership := self._case_memberships.get(key), CaseMembership)
        )
