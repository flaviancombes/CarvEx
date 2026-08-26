"""Sous-présentateurs réutilisables du provider Details Investigation."""

from __future__ import annotations

from dataclasses import replace

from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.hypothesis import HypothesisConfidence, HypothesisRole, HypothesisStatus, InvestigationHypothesisId
from investigation.item import InvestigationItemId
from investigation.note import InvestigationNoteId
from investigation.relation import InvestigationRelationType
from investigation.target_ref import InvestigationTargetRef
from selection.canonical_entity_resolver import CanonicalEntityResolver
from selection.context import SelectionContext
from ui.details_providers import DetailsPanelHost


class InvestigationTargetRenderer:
    """Produit les libellés et icônes sans donner accès aux widgets Qt."""

    def __init__(self, service) -> None:
        self._service = service

    def label(self, target: InvestigationTargetRef) -> str:
        if target.target_kind == "file":
            item = self._service.find_item_by_subject("file", target.target_id)
            return item.title or "Preuve" if item is not None else "Fichier"
        if target.target_kind == "item":
            item = self._service.get_item(InvestigationItemId(target.target_id))
            return item.title or item.subject_kind if item is not None else "Élément supprimé"
        if target.target_kind == "note":
            note = self._service.get_note(InvestigationNoteId(target.target_id))
            return self.split_note(note.body)[0] or "Note" if note is not None else "Note supprimée"
        if target.target_kind == "hypothesis":
            value = self._service.get_hypothesis(InvestigationHypothesisId(target.target_id))
        elif target.target_kind == "case":
            value = self._service.get_case(InvestigationCaseId(target.target_id))
        else:
            value = self._service.get_collection(InvestigationCollectionId(target.target_id))
        return value.title if value is not None else "Objet supprimé"

    def with_icon(self, target: InvestigationTargetRef) -> str:
        icon = {"item": "📄", "note": "📝", "hypothesis": "💡", "collection": "📂"}.get(target.target_kind, "📄")
        return f"{icon} {self.label(target)}"

    @staticmethod
    def split_note(body: str) -> tuple[str, str]:
        return body.split("\n\n", 1) if "\n\n" in body else ("", body)


class InvestigationRelationRenderer:
    """Centralise le vocabulaire de relation affiché à l'enquêteur."""

    @staticmethod
    def phrase(relation_type: InvestigationRelationType) -> str:
        return {
            InvestigationRelationType.RELATED_TO: "est lié à",
            InvestigationRelationType.CONFIRMS: "soutient",
            InvestigationRelationType.CONTRADICTS: "contredit",
            InvestigationRelationType.DERIVED_FROM: "dérive de",
            InvestigationRelationType.DUPLICATES: "duplique",
            InvestigationRelationType.REFERENCES: "référence",
        }[relation_type]


class InvestigationDetailsNavigation:
    """Construit les intentions de navigation sans conserver d'état Qt."""

    @staticmethod
    def target_context(
        target: InvestigationTargetRef,
        origin: str,
        navigation_hint: dict[str, str],
        current_kind: str | None,
        current_id: str | None,
        current_title: str,
    ) -> SelectionContext:
        hint = dict(navigation_hint)
        if current_kind in {"case", "collection"} and current_id is not None:
            hint.update(
                {
                    "container_kind": current_kind,
                    "container_id": current_id,
                    "container_title": current_title,
                }
            )
        return SelectionContext(target.target_kind, target.target_id, origin, navigation_hint=hint)


class InvestigationMembershipActions:
    """Isole les commandes d'appartenance de leur présentation Qt."""

    @staticmethod
    def remove(service, container_kind: str | None, container_id: str | None, target: InvestigationTargetRef) -> None:
        if container_kind == "case" and container_id is not None:
            service.remove_from_case(InvestigationCaseId(container_id), target)
        elif container_kind == "collection" and container_id is not None:
            service.remove_from_collection(InvestigationCollectionId(container_id), target)


class InvestigationDetailsEditor:
    """Applique les commandes d'édition via le seul service public."""

    def __init__(self, service, queries) -> None:
        self._service = service
        self._queries = queries

    def save(
        self,
        kind: str,
        object_id: str,
        *,
        name: str,
        description: str,
        subject_kind: str,
        content: str,
        confidence: str,
        status: str,
        evidence_note: str,
        evidence_hypothesis: str,
    ) -> None:
        if kind == "item":
            item = self._service.get_item(InvestigationItemId(object_id))
            if item is None:
                return
            updated = self._service.update_item(
                replace(item, title=name or None, summary=description or None, subject_kind=subject_kind)
            )
            item_ref = InvestigationTargetRef("item", str(updated.item_id))
            context = self._queries.get_target_context(item_ref)
            if evidence_note:
                if context.notes:
                    self._service.update_note(replace(context.notes[0], body=evidence_note))
                else:
                    self._service.create_note(evidence_note, target_ref=item_ref)
            if evidence_hypothesis:
                if context.hypotheses:
                    self._service.update_hypothesis(replace(context.hypotheses[0], title=evidence_hypothesis))
                else:
                    hypothesis = self._service.create_hypothesis(evidence_hypothesis)
                    self._service.add_to_hypothesis(hypothesis.hypothesis_id, item_ref, HypothesisRole.OBSERVATION)
            return
        if kind == "note":
            note = self._service.get_note(InvestigationNoteId(object_id))
            if note is not None:
                self._service.update_note(replace(note, body=f"{description}\n\n{content}" if description else content))
            return
        if kind == "hypothesis":
            hypothesis = self._service.get_hypothesis(InvestigationHypothesisId(object_id))
            if hypothesis is not None:
                self._service.update_hypothesis(
                    replace(
                        hypothesis,
                        title=name,
                        description=description or None,
                        confidence=HypothesisConfidence(confidence),
                        status=HypothesisStatus(status),
                    )
                )
            return
        if kind == "case":
            case = self._service.get_case(InvestigationCaseId(object_id))
            if case is not None:
                self._service.update_case(replace(case, title=name, description=description or None))
            return
        collection = self._service.get_collection(InvestigationCollectionId(object_id))
        if collection is not None:
            self._service.update_collection(replace(collection, title=name, description=description or None))


class InvestigationJournalRenderer:
    """Formate une entrée de journal sans exposer son vocabulaire technique au widget."""

    @staticmethod
    def label(entry) -> str:
        return f"{entry.timestamp.astimezone().strftime('%Y-%m-%d %H:%M:%S')} — {entry.event_type.value}"


class InvestigationPreviewBridge:
    """Réutilise explicitement le rendu Fichier pour une preuve liée."""

    def __init__(self, entity_resolver: CanonicalEntityResolver) -> None:
        self._entity_resolver = entity_resolver

    def present(self, panel: DetailsPanelHost, value, context: SelectionContext, widget) -> bool:
        resolved = self._entity_resolver.resolve(value)
        if context.subject_kind != "item" or resolved is None or not resolved.is_file:
            return False
        file_context = SelectionContext("file", resolved.identifier, "investigation_evidence")
        if not panel.populate_file_context(file_context):
            return False
        widget.set_file_presentation_name(panel.current_file_title())
        panel.show_file_extension_widget(widget)
        return True
