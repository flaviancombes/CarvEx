"""Projections de lecture du domaine Investigation, sans Qt ni persistance."""

from __future__ import annotations

from dataclasses import dataclass

from investigation.case import InvestigationCase, InvestigationCaseId
from investigation.collection import InvestigationCollection, InvestigationCollectionId
from investigation.hypothesis import HypothesisMembership, InvestigationHypothesis, InvestigationHypothesisId
from investigation.item import InvestigationItem
from investigation.journal import InvestigationJournalEntry
from investigation.note import InvestigationNote
from investigation.relation import InvestigationRelation
from investigation.service import InvestigationService
from investigation.tag import InvestigationTag
from investigation.target_ref import InvestigationTargetRef


@dataclass(frozen=True, slots=True)
class InvestigationTargetContext:
    """Projection des associations directes d'une référence Investigation."""

    target_ref: InvestigationTargetRef
    item: InvestigationItem | None
    notes: tuple[InvestigationNote, ...]
    tags: tuple[InvestigationTag, ...]
    relations: tuple[InvestigationRelation, ...]
    collections: tuple[InvestigationCollection, ...]
    cases: tuple[InvestigationCase, ...]
    hypotheses: tuple[InvestigationHypothesis, ...]
    journal_entries: tuple[InvestigationJournalEntry, ...]


@dataclass(frozen=True, slots=True)
class InvestigationCaseContext:
    """Projection directe d'une Case, sans parcourir tous ses membres."""

    case: InvestigationCase
    members: tuple[InvestigationTargetRef, ...]
    notes: tuple[InvestigationNote, ...]
    tags: tuple[InvestigationTag, ...]
    collections: tuple[InvestigationCollection, ...]
    hypotheses: tuple[InvestigationHypothesis, ...]


@dataclass(frozen=True, slots=True)
class InvestigationCollectionContext:
    """Projection directe d'une Collection et de ses annotations associées."""

    collection: InvestigationCollection
    members: tuple[InvestigationTargetRef, ...]
    notes: tuple[InvestigationNote, ...]
    tags: tuple[InvestigationTag, ...]


@dataclass(frozen=True, slots=True)
class InvestigationHypothesisContext:
    """Projection d'un raisonnement avec les rôles typés de ses membres."""

    hypothesis: InvestigationHypothesis
    memberships: tuple[HypothesisMembership, ...]
    relations: tuple[InvestigationRelation, ...]


class InvestigationQueryService:
    """Façade de lecture composée exclusivement à partir de l'API métier publique.

    Chaque projection s'appuie sur les index maintenus par le domaine. Aucune
    donnée n'est persistée, modifiée ou publiée par ce composant.
    """

    def __init__(self, service: InvestigationService) -> None:
        self._service = service

    def get_target_context(self, target_ref: InvestigationTargetRef) -> InvestigationTargetContext:
        """Retourne les associations directes d'une cible, sans exploration de graphe."""
        return InvestigationTargetContext(
            target_ref=target_ref,
            item=self._service.find_item_by_subject(target_ref.target_kind, target_ref.target_id),
            notes=self._service.find_notes_for_target(target_ref),
            tags=self._service.find_tags_for_target(target_ref),
            relations=self._service.find_relations_for_target(target_ref),
            collections=self._service.find_collections_for_target(target_ref),
            cases=self._service.find_cases_for_target(target_ref),
            hypotheses=self._service.find_hypotheses_for_target(target_ref),
            journal_entries=self._service.find_entries_for_target(target_ref),
        )

    def get_case_context(self, case_id: InvestigationCaseId) -> InvestigationCaseContext:
        case = self._require_case(case_id)
        direct_context = self.get_target_context(self._entity_ref("case", case.case_id))
        return InvestigationCaseContext(
            case=case,
            members=self._service.find_case_members(case_id),
            notes=direct_context.notes,
            tags=direct_context.tags,
            collections=direct_context.collections,
            hypotheses=direct_context.hypotheses,
        )

    def get_collection_context(self, collection_id: InvestigationCollectionId) -> InvestigationCollectionContext:
        collection = self._require_collection(collection_id)
        direct_context = self.get_target_context(self._entity_ref("collection", collection.collection_id))
        return InvestigationCollectionContext(
            collection=collection,
            members=self._service.find_collection_members(collection_id),
            notes=direct_context.notes,
            tags=direct_context.tags,
        )

    def get_hypothesis_context(self, hypothesis_id: InvestigationHypothesisId) -> InvestigationHypothesisContext:
        hypothesis = self._require_hypothesis(hypothesis_id)
        direct_context = self.get_target_context(self._entity_ref("hypothesis", hypothesis.hypothesis_id))
        return InvestigationHypothesisContext(
            hypothesis=hypothesis,
            memberships=self._service.find_hypothesis_memberships(hypothesis_id),
            relations=direct_context.relations,
        )

    def get_journal_for_target(self, target_ref: InvestigationTargetRef) -> tuple[InvestigationJournalEntry, ...]:
        return self._service.find_entries_for_target(target_ref)

    def _require_case(self, case_id: InvestigationCaseId) -> InvestigationCase:
        case = self._service.get_case(case_id)
        if case is None:
            raise KeyError(f"InvestigationCase introuvable : {case_id}")
        return case

    def _require_collection(self, collection_id: InvestigationCollectionId) -> InvestigationCollection:
        collection = self._service.get_collection(collection_id)
        if collection is None:
            raise KeyError(f"InvestigationCollection introuvable : {collection_id}")
        return collection

    def _require_hypothesis(self, hypothesis_id: InvestigationHypothesisId) -> InvestigationHypothesis:
        hypothesis = self._service.get_hypothesis(hypothesis_id)
        if hypothesis is None:
            raise KeyError(f"InvestigationHypothesis introuvable : {hypothesis_id}")
        return hypothesis

    @staticmethod
    def _entity_ref(kind: str, identifier: str) -> InvestigationTargetRef:
        return InvestigationTargetRef(kind, str(identifier))
