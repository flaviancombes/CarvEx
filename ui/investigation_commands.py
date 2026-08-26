"""Commandes UI Investigation, isolées des widgets Qt."""

from __future__ import annotations

from uuid import uuid4

from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.hypothesis import HypothesisConfidence, HypothesisRole, HypothesisStatus
from investigation.relation import InvestigationRelationType
from investigation.service import InvestigationService
from investigation.target_ref import InvestigationTargetRef
from models.investigation_tree_model import InvestigationTreeEntry
from selection.canonical_entity_resolver import CanonicalEntityResolver


class InvestigationCommandGateway:
    """Traduit les intentions UI en appels exclusifs à ``InvestigationService``."""

    def __init__(self, service: InvestigationService, entity_resolver: CanonicalEntityResolver | None = None) -> None:
        self._service = service
        self._entity_resolver = entity_resolver

    def create_item(self, title: str, description: str, subject_kind: str):
        return self._service.create_item(
            subject_kind.strip() or "manual",
            str(uuid4()),
            title=title.strip(),
            summary=description.strip() or None,
        )

    def create_note(self, title: str, body: str, target_ref: InvestigationTargetRef | None = None):
        content = body.strip() if not title.strip() else f"{title.strip()}\n\n{body.strip()}"
        return self._service.create_note(content, target_ref=target_ref)

    def create_hypothesis(
        self,
        title: str,
        description: str,
        confidence: str,
        status: str,
        target_ref: InvestigationTargetRef | None = None,
    ):
        hypothesis = self._service.create_hypothesis(
            title.strip(),
            description=description.strip() or None,
            confidence=HypothesisConfidence(confidence),
            status=HypothesisStatus(status),
        )
        if target_ref is not None:
            self._service.add_to_hypothesis(hypothesis.hypothesis_id, target_ref, HypothesisRole.OBSERVATION)
        return hypothesis

    def add_file_item(self, file_id: str, title: str):
        return self.add_target_item(InvestigationTargetRef("file", file_id), title)

    def add_target_item(self, target: InvestigationTargetRef, title: str):
        resolved = self._entity_resolver.resolve(target) if self._entity_resolver is not None else None
        if resolved is not None and resolved.is_file:
            target = InvestigationTargetRef("file", resolved.identifier)
        existing = self._service.find_item_by_subject(target.target_kind, target.target_id)
        return existing or self._service.create_item(target.target_kind, target.target_id, title=title)

    def has_file_item(self, file_id: str) -> bool:
        return self.has_target_item(InvestigationTargetRef("file", file_id))

    def has_target_item(self, target: InvestigationTargetRef) -> bool:
        return self._service.find_item_by_subject(target.target_kind, target.target_id) is not None

    def create_case(self, title: str, description: str):
        return self._service.create_case(title.strip(), description=description.strip() or None)

    def create_collection(self, title: str, description: str):
        return self._service.create_collection(title.strip(), description=description.strip() or None)

    def relation_targets(self) -> tuple[tuple[str, str, str], ...]:
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
        return tuple((value.value.replace("_", " ").title(), value.value) for value in InvestigationRelationType)

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

    @staticmethod
    def _summary(value: str, limit: int = 90) -> str:
        compact = " ".join(value.split())
        return compact if len(compact) <= limit else f"{compact[: limit - 1]}…"
