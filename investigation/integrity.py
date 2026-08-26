"""Diagnostic de cohérence du domaine Investigation, sans effet de bord."""

# ruff: noqa: I001, UP042
# Exceptions are limited to this legacy persisted-model module.
from __future__ import annotations

# ruff: noqa: UP042
# L'enum conserve la représentation publique historique des rapports d'intégrité.

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from investigation.case import InvestigationCaseId
from investigation.collection import InvestigationCollectionId
from investigation.hypothesis import HypothesisRole, InvestigationHypothesisId
from investigation.item import InvestigationItemId
from investigation.note import InvestigationNoteId
from investigation.relation import InvestigationRelation, InvestigationRelationId
from investigation.service import InvestigationService
from investigation.tag import InvestigationTagId
from investigation.target_ref import InvestigationTargetRef


class IntegrityIssueSeverity(
    str, Enum
):  # noqa: UP042 - Préserve la compatibilité de représentation publique des projets existants.
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    """Constat de diagnostic immuable ; le validateur ne le corrige jamais."""

    severity: IntegrityIssueSeverity
    code: str
    description: str
    target_ref: InvestigationTargetRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.severity, IntegrityIssueSeverity):
            raise ValueError("La gravité d'un problème d'intégrité doit être typée.")
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("Un problème d'intégrité doit avoir un code stable.")
        if not isinstance(self.description, str) or not self.description:
            raise ValueError("Un problème d'intégrité doit être décrit.")
        if self.target_ref is not None and not isinstance(self.target_ref, InvestigationTargetRef):
            raise ValueError("La cible d'un problème d'intégrité doit être valide.")


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Résultat complet et immuable d'une validation ponctuelle."""

    issues: tuple[IntegrityIssue, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(issue, IntegrityIssue) for issue in self.issues):
            raise ValueError("Un rapport d'intégrité ne contient que des problèmes typés.")

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity is IntegrityIssueSeverity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity is IntegrityIssueSeverity.WARNING for issue in self.issues)


TargetExistsResolver = Callable[[InvestigationTargetRef], bool | None]


class InvestigationIntegrityValidator:
    """Contrôle les projections publiques du domaine sans y écrire.

    Le résolveur optionnel permet aux modules propriétaires de cibles externes
    (fichiers, Timeline, Registry…) de confirmer leur existence. `None` signifie
    que la référence est hors du périmètre du résolveur et ne constitue pas une
    erreur à elle seule.
    """

    _KNOWN_TARGET_KINDS = {
        "investigation_item": InvestigationItemId,
        "item": InvestigationItemId,
        "case": InvestigationCaseId,
        "collection": InvestigationCollectionId,
        "hypothesis": InvestigationHypothesisId,
        "note": InvestigationNoteId,
        "tag": InvestigationTagId,
        "relation": InvestigationRelationId,
    }

    def __init__(
        self,
        service: InvestigationService,
        target_exists: TargetExistsResolver | None = None,
    ) -> None:
        self._service = service
        self._target_exists = target_exists

    def validate(self) -> IntegrityReport:
        """Exécute un diagnostic complet, sans reconstruire ni modifier d'index."""
        issues: list[IntegrityIssue] = []
        self._validate_items(issues)
        self._validate_relations(issues)
        self._validate_cases(issues)
        self._validate_collections(issues)
        self._validate_hypotheses(issues)
        self._validate_notes(issues)
        self._validate_tags(issues)
        self._validate_journal(issues)
        return IntegrityReport(tuple(issues))

    def _validate_items(self, issues: list[IntegrityIssue]) -> None:
        for item in self._service.list_items():
            self._validate_target(
                InvestigationTargetRef(item.subject_kind, item.subject_id),
                "orphan_item_subject",
                "L'Item référence un sujet inexistant.",
                issues,
            )

    def _validate_relations(self, issues: list[IntegrityIssue]) -> None:
        signatures: set[tuple[object, InvestigationTargetRef, InvestigationTargetRef]] = set()
        for relation in self._service.list_relations():
            self._validate_target(
                relation.source_target,
                "orphan_relation_source",
                "La relation référence une source inexistante.",
                issues,
            )
            self._validate_target(
                relation.destination_target,
                "orphan_relation_destination",
                "La relation référence une destination inexistante.",
                issues,
            )
            if relation.source_target == relation.destination_target and not relation.semantics.allows_self_reference:
                self._issue(
                    issues,
                    IntegrityIssueSeverity.ERROR,
                    "forbidden_relation_self_reference",
                    "La relation contient une auto-référence interdite.",
                    relation.source_target,
                )
            signature = self._relation_signature(relation)
            if signature in signatures:
                self._issue(
                    issues,
                    IntegrityIssueSeverity.ERROR,
                    "duplicate_logical_relation",
                    "Une relation logique identique existe déjà.",
                    relation.source_target,
                )
            signatures.add(signature)

    def _validate_cases(self, issues: list[IntegrityIssue]) -> None:
        for case in self._service.list_cases():
            self._validate_members(
                self._service.find_case_members(case.case_id),
                "duplicate_case_membership",
                "orphan_case_membership",
                issues,
            )

    def _validate_collections(self, issues: list[IntegrityIssue]) -> None:
        for collection in self._service.list_collections():
            self._validate_members(
                self._service.find_collection_members(collection.collection_id),
                "duplicate_collection_membership",
                "orphan_collection_membership",
                issues,
            )

    def _validate_hypotheses(self, issues: list[IntegrityIssue]) -> None:
        for hypothesis in self._service.list_hypotheses():
            seen: set[InvestigationTargetRef] = set()
            for membership in self._service.find_hypothesis_memberships(hypothesis.hypothesis_id):
                if not isinstance(membership.target_ref, InvestigationTargetRef):
                    self._issue(
                        issues,
                        IntegrityIssueSeverity.ERROR,
                        "invalid_hypothesis_membership",
                        "Un membre d'hypothèse ne référence pas une cible valide.",
                        None,
                    )
                    continue
                if membership.target_ref in seen:
                    self._issue(
                        issues,
                        IntegrityIssueSeverity.ERROR,
                        "duplicate_hypothesis_membership",
                        "Une cible est présente plusieurs fois dans l'hypothèse.",
                        membership.target_ref,
                    )
                seen.add(membership.target_ref)
                if not isinstance(membership.role, HypothesisRole):
                    self._issue(
                        issues,
                        IntegrityIssueSeverity.ERROR,
                        "invalid_hypothesis_role",
                        "Le rôle d'un membre d'hypothèse est invalide.",
                        membership.target_ref,
                    )
                self._validate_target(
                    membership.target_ref,
                    "orphan_hypothesis_membership",
                    "Un membre d'hypothèse référence une cible inexistante.",
                    issues,
                )

    def _validate_notes(self, issues: list[IntegrityIssue]) -> None:
        for note in self._service.list_notes():
            if note.target_ref is not None:
                self._validate_target(
                    note.target_ref, "orphan_note_target", "La note référence une cible inexistante.", issues
                )

    def _validate_tags(self, issues: list[IntegrityIssue]) -> None:
        for tag in self._service.list_tags():
            self._validate_members(
                self._service.find_targets_for_tag(tag.tag_id),
                "duplicate_tag_assignment",
                "orphan_tag_assignment",
                issues,
            )

    def _validate_journal(self, issues: list[IntegrityIssue]) -> None:
        for entry in self._service.list_entries():
            if entry.target_ref is not None:
                self._validate_target(
                    entry.target_ref,
                    "orphan_journal_target",
                    "L'entrée de Journal référence une cible inexistante.",
                    issues,
                )

    def _validate_members(
        self,
        members: tuple[InvestigationTargetRef, ...],
        duplicate_code: str,
        orphan_code: str,
        issues: list[IntegrityIssue],
    ) -> None:
        seen: set[InvestigationTargetRef] = set()
        for target_ref in members:
            if not isinstance(target_ref, InvestigationTargetRef):
                self._issue(
                    issues,
                    IntegrityIssueSeverity.ERROR,
                    orphan_code,
                    "Un membership référence une cible invalide.",
                    None,
                )
                continue
            if target_ref in seen:
                self._issue(
                    issues,
                    IntegrityIssueSeverity.ERROR,
                    duplicate_code,
                    "Une association logique est dupliquée.",
                    target_ref,
                )
            seen.add(target_ref)
            self._validate_target(target_ref, orphan_code, "Un membership référence une cible inexistante.", issues)

    def _validate_target(
        self,
        target_ref: InvestigationTargetRef,
        code: str,
        description: str,
        issues: list[IntegrityIssue],
    ) -> None:
        if not isinstance(target_ref, InvestigationTargetRef):
            self._issue(issues, IntegrityIssueSeverity.ERROR, code, description, None)
            return
        exists = self._known_target_exists(target_ref)
        if exists is None and self._target_exists is not None:
            exists = self._target_exists(target_ref)
        if exists is False:
            self._issue(issues, IntegrityIssueSeverity.ERROR, code, description, target_ref)

    def _known_target_exists(self, target_ref: InvestigationTargetRef) -> bool | None:
        identifier_type = self._KNOWN_TARGET_KINDS.get(target_ref.target_kind)
        if identifier_type is None:
            return None
        identifier = identifier_type(target_ref.target_id)
        if target_ref.target_kind in {"investigation_item", "item"}:
            return self._service.get_item(identifier) is not None
        if target_ref.target_kind == "case":
            return self._service.get_case(identifier) is not None
        if target_ref.target_kind == "collection":
            return self._service.get_collection(identifier) is not None
        if target_ref.target_kind == "hypothesis":
            return self._service.get_hypothesis(identifier) is not None
        if target_ref.target_kind == "note":
            return self._service.get_note(identifier) is not None
        if target_ref.target_kind == "tag":
            return self._service.get_tag(identifier) is not None
        if target_ref.target_kind == "relation":
            return self._service.get_relation(identifier) is not None
        return None

    @staticmethod
    def _relation_signature(
        relation: InvestigationRelation,
    ) -> tuple[object, InvestigationTargetRef, InvestigationTargetRef]:
        source, destination = relation.source_target, relation.destination_target
        if relation.semantics.symmetric and destination.sort_key < source.sort_key:
            source, destination = destination, source
        return relation.relation_type, source, destination

    @staticmethod
    def _issue(
        issues: list[IntegrityIssue],
        severity: IntegrityIssueSeverity,
        code: str,
        description: str,
        target_ref: InvestigationTargetRef | None,
    ) -> None:
        issues.append(IntegrityIssue(severity, code, description, target_ref))
