"""Projection lisible du Journal Investigation pour l'arborescence Qt."""

from __future__ import annotations

from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.events import EventType
from investigation.hypothesis import InvestigationHypothesisId
from investigation.item import InvestigationItemId
from investigation.journal import InvestigationJournalEntry
from investigation.note import InvestigationNoteId
from investigation.target_ref import InvestigationTargetRef
from models.investigation_tree_model import InvestigationTreeEntry


class InvestigationJournalFormatter:
    """Formate le Journal via les API publiques du service, sans persistance."""

    def __init__(self, service) -> None:
        self._service = service

    def entry(self, value: InvestigationJournalEntry) -> InvestigationTreeEntry:
        timestamp = value.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        action = {
            EventType.ITEM_CREATED: "Nouvelle preuve",
            EventType.ITEM_UPDATED: "Preuve modifiée",
            EventType.NOTE_CREATED: "Post-it ajouté" if self._is_post_it(value) else "Note ajoutée",
            EventType.NOTE_UPDATED: "Post-it modifié" if self._is_post_it(value) else "Note modifiée",
            EventType.HYPOTHESIS_CREATED: "Hypothèse créée",
            EventType.HYPOTHESIS_UPDATED: "Modification d'une hypothèse",
            EventType.RELATION_CREATED: "Création d'une relation",
            EventType.MEMBERSHIP_ADDED: "Organisation mise à jour",
        }.get(value.event_type, value.event_type.value.replace("_", " ").capitalize())
        return InvestigationTreeEntry(
            "journal_entry",
            str(value.entry_id),
            action,
            f"{timestamp} — {self._label(value)}",
            related_target_ref=value.target_ref,
        )

    def _label(self, entry: InvestigationJournalEntry) -> str:
        target_label = (
            self._target_label(entry.target_ref) if entry.target_ref is not None else self._entity_label(entry)
        )
        if entry.event_type is EventType.MEMBERSHIP_ADDED and entry.parent_ref is not None:
            return f"{target_label} ajouté à {self._target_label(entry.parent_ref)}"
        if entry.event_type is EventType.MEMBERSHIP_REMOVED and entry.parent_ref is not None:
            return f"{target_label} retiré de {self._target_label(entry.parent_ref)}"
        if entry.event_type is EventType.RELATION_CREATED:
            kind = entry.context.get("related_target_kind")
            identifier = entry.context.get("related_target_id")
            if kind and identifier:
                return f"{target_label} lié à {self._target_label(InvestigationTargetRef(kind, identifier))}"
        return target_label

    @staticmethod
    def _is_post_it(entry: InvestigationJournalEntry) -> bool:
        return entry.target_ref is None or entry.target_ref.target_kind in {"case", "collection"}

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

    @staticmethod
    def _summary(value: str, limit: int = 90) -> str:
        compact = " ".join(value.split())
        return compact if len(compact) <= limit else f"{compact[: limit - 1]}…"
