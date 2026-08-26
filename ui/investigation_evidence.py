"""Workflow Evidence de l'interface Investigation, sans widget Qt."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.hypothesis import HypothesisRole
from investigation.queries import InvestigationQueryService
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from selection.canonical_entity_resolver import CanonicalEntityResolver


@dataclass(frozen=True, slots=True)
class EvidenceFormContext:
    """Projection légère nécessaire au dialogue Evidence partagé."""

    existing: bool
    display_name: str
    note: str
    hypothesis: str
    selected_case_id: str | None
    selected_collection_id: str | None
    cases: tuple[tuple[str, str], ...]
    collections: tuple[tuple[str, str], ...]


class InvestigationEvidenceWorkflow:
    """Prépare et applique les commandes Evidence via le service public."""

    def __init__(
        self,
        service: InvestigationService,
        queries: InvestigationQueryService,
        commands,
        entity_resolver: CanonicalEntityResolver | None = None,
    ) -> None:
        self._service = service
        self._queries = queries
        self._commands = commands
        self._entity_resolver = entity_resolver

    def form_context(self, target: InvestigationTargetRef, fallback_name: str) -> EvidenceFormContext:
        target = self._canonical_target(target)
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
                self._commands.containers("case"),
                self._commands.containers("collection"),
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
            self._commands.containers("case"),
            self._commands.containers("collection"),
        )

    def save(
        self,
        target: InvestigationTargetRef,
        *,
        display_name: str,
        note: str,
        hypothesis: str,
        case_id: str | None,
        collection_id: str | None,
    ):
        target = self._canonical_target(target)
        source_context = self._queries.get_target_context(target)
        item = source_context.item
        now = datetime.now(UTC)
        if item is None:
            item = self._service.create_item(target.target_kind, target.target_id, title=display_name)
        elif item.title != display_name:
            item = self._service.update_item(replace(item, title=display_name, updated_at=now))
        item_ref = InvestigationTargetRef("item", str(item.item_id))
        item_context = self._queries.get_target_context(item_ref)
        self._save_note(item_context.notes or source_context.notes, item_ref, note, now)
        self._save_hypothesis(item_context.hypotheses or source_context.hypotheses, item_ref, hypothesis, now)
        self._synchronise_container(item_context.cases, item_ref, case_id, "case")
        self._synchronise_container(item_context.collections, item_ref, collection_id, "collection")
        return item

    def _canonical_target(self, target: InvestigationTargetRef) -> InvestigationTargetRef:
        resolved = self._entity_resolver.resolve(target) if self._entity_resolver is not None else None
        return (
            InvestigationTargetRef("file", resolved.identifier) if resolved is not None and resolved.is_file else target
        )

    def _save_note(self, notes, item_ref: InvestigationTargetRef, body: str, now: datetime) -> None:
        content = body.strip()
        if not content:
            return
        if notes:
            note = notes[0]
            if note.body != content or note.target_ref != item_ref:
                self._service.update_note(replace(note, body=content, target_ref=item_ref, updated_at=now))
            return
        self._service.create_note(content, target_ref=item_ref)

    def _save_hypothesis(self, hypotheses, item_ref: InvestigationTargetRef, title: str, now: datetime) -> None:
        value = title.strip()
        if not value:
            return
        hypothesis = hypotheses[0] if hypotheses else self._service.create_hypothesis(value)
        if hypothesis.title != value:
            hypothesis = self._service.update_hypothesis(replace(hypothesis, title=value, updated_at=now))
        memberships = self._queries.get_hypothesis_context(hypothesis.hypothesis_id).memberships
        if all(membership.target_ref != item_ref for membership in memberships):
            self._service.add_to_hypothesis(hypothesis.hypothesis_id, item_ref, HypothesisRole.OBSERVATION)

    def _synchronise_container(
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
