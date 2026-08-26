"""Déclaration du module Investigation dans le système de projets."""

from __future__ import annotations

from investigation.events import EventBus, EventType
from investigation.integrity import InvestigationIntegrityValidator
from investigation.journal import InvestigationJournalEntry, JournalSubscriber
from investigation.manager import InvestigationManager
from investigation.physical_representation import InvestigationPhysicalRepresentationService
from investigation.queries import InvestigationQueryService
from investigation.repository import InvestigationRepository
from investigation.service import InvestigationService
from project.codecs import ProjectCodecRegistry, dataclass_codec, enum_codec
from project.migrations import ModuleMigrationService
from project.modules import ModuleDescriptor, ProjectModule, ProjectModuleContext


class InvestigationProjectModule(ProjectModule):
    """Module déclaratif : infrastructure seulement pour la phase 1."""

    REPOSITORY_NAME = "repository"
    SERVICE_NAME = "service"
    JOURNAL_SUBSCRIBER_NAME = "journal_subscriber"
    QUERY_SERVICE_NAME = "query_service"
    INTEGRITY_VALIDATOR_NAME = "integrity_validator"
    PHYSICAL_REPRESENTATION_NAME = "physical_representation"

    def migrations(self) -> ModuleMigrationService:
        migrations = ModuleMigrationService(self.descriptor.module_id)
        migrations.register(1, self._migrate_v1_to_v2)
        migrations.register(2, self._migrate_v2_to_v3)
        migrations.register(3, self._migrate_v3_to_v4)
        return migrations

    @staticmethod
    def _migrate_v1_to_v2(context: ProjectModuleContext) -> None:
        """Déclare les stores logiques de Collections, sans créer de donnée primaire."""
        context.store(InvestigationRepository.COLLECTIONS_STORE)
        context.store(InvestigationRepository.COLLECTION_MEMBERSHIPS_STORE)

    @staticmethod
    def _migrate_v2_to_v3(context: ProjectModuleContext) -> None:
        """Déclare les stores logiques d'Hypothèses sans créer de donnée primaire."""
        context.store(InvestigationRepository.HYPOTHESES_STORE)
        context.store(InvestigationRepository.HYPOTHESIS_MEMBERSHIPS_STORE)

    @staticmethod
    def _migrate_v3_to_v4(context: ProjectModuleContext) -> None:
        """Déclare le store append-only du Journal sans créer de donnée primaire."""
        context.store(InvestigationRepository.JOURNAL_STORE)

    def register_codecs(self, registry: ProjectCodecRegistry) -> None:
        """Déclare la persistance Investigation sans exposer ses types au storage."""
        from investigation.case import CaseMembership, CasePriority, CaseStatus, InvestigationCase
        from investigation.collection import CollectionMembership, InvestigationCollection
        from investigation.hypothesis import (
            HypothesisConfidence,
            HypothesisMembership,
            HypothesisRole,
            HypothesisStatus,
            InvestigationHypothesis,
        )
        from investigation.item import InvestigationItem, InvestigationPriority, InvestigationStatus
        from investigation.note import InvestigationNote, InvestigationNoteFormat
        from investigation.relation import InvestigationRelation, InvestigationRelationType
        from investigation.tag import InvestigationTag, TagAssignment
        from investigation.target_ref import InvestigationTargetRef

        registry.register_many(
            [
                dataclass_codec("dataclass:investigation.item.InvestigationItem", InvestigationItem),
                enum_codec("enum:investigation.item.InvestigationPriority", InvestigationPriority),
                enum_codec("enum:investigation.item.InvestigationStatus", InvestigationStatus),
                dataclass_codec("dataclass:investigation.collection.InvestigationCollection", InvestigationCollection),
                dataclass_codec("dataclass:investigation.collection.CollectionMembership", CollectionMembership),
                dataclass_codec("dataclass:investigation.hypothesis.InvestigationHypothesis", InvestigationHypothesis),
                dataclass_codec("dataclass:investigation.hypothesis.HypothesisMembership", HypothesisMembership),
                enum_codec("enum:investigation.hypothesis.HypothesisStatus", HypothesisStatus),
                enum_codec("enum:investigation.hypothesis.HypothesisConfidence", HypothesisConfidence),
                enum_codec("enum:investigation.hypothesis.HypothesisRole", HypothesisRole),
                dataclass_codec("dataclass:investigation.journal.InvestigationJournalEntry", InvestigationJournalEntry),
                enum_codec("enum:investigation.events.EventType", EventType),
                dataclass_codec("dataclass:investigation.case.InvestigationCase", InvestigationCase),
                dataclass_codec("dataclass:investigation.case.CaseMembership", CaseMembership),
                enum_codec("enum:investigation.case.CasePriority", CasePriority),
                enum_codec("enum:investigation.case.CaseStatus", CaseStatus),
                dataclass_codec("dataclass:investigation.note.InvestigationNote", InvestigationNote),
                enum_codec("enum:investigation.note.InvestigationNoteFormat", InvestigationNoteFormat),
                dataclass_codec("dataclass:investigation.relation.InvestigationRelation", InvestigationRelation),
                enum_codec("enum:investigation.relation.InvestigationRelationType", InvestigationRelationType),
                dataclass_codec("dataclass:investigation.tag.InvestigationTag", InvestigationTag),
                dataclass_codec("dataclass:investigation.tag.TagAssignment", TagAssignment),
                dataclass_codec("dataclass:investigation.target_ref.InvestigationTargetRef", InvestigationTargetRef),
            ]
        )

    @property
    def descriptor(self) -> ModuleDescriptor:
        return ModuleDescriptor(
            module_id=InvestigationRepository.MODULE_ID,
            schema_version=4,
            capabilities_provided=frozenset({"investigation"}),
            store_names=InvestigationRepository.STORE_NAMES,
        )

    def initialize(self, context: ProjectModuleContext) -> None:
        repository = InvestigationRepository({name: context.store(name) for name in self.descriptor.store_names})
        manager = InvestigationManager(repository)
        event_bus = EventBus()
        service = InvestigationService(manager, event_bus)
        query_service = InvestigationQueryService(service)
        integrity_validator = InvestigationIntegrityValidator(service)
        subscriber = JournalSubscriber(manager)
        subscriber.subscribe(event_bus)
        representation = InvestigationPhysicalRepresentationService(service, context.repository.physical_root)
        context.register_repository(self.REPOSITORY_NAME, repository)
        context.register_repository(self.SERVICE_NAME, service)
        context.register_repository(self.QUERY_SERVICE_NAME, query_service)
        context.register_repository(self.INTEGRITY_VALIDATOR_NAME, integrity_validator)
        context.register_repository(self.JOURNAL_SUBSCRIBER_NAME, subscriber)
        context.register_repository(self.PHYSICAL_REPRESENTATION_NAME, representation)

    def open(self, context: ProjectModuleContext) -> None:
        self._service(context).open()
        self._representation(context).open()

    def close(self, context: ProjectModuleContext) -> None:
        self._representation(context).close()
        subscriber = context.repository.module_repository(self.descriptor.module_id, self.JOURNAL_SUBSCRIBER_NAME)
        if isinstance(subscriber, JournalSubscriber):
            event_bus = self._service(context).event_bus
            if event_bus is not None:
                subscriber.unsubscribe(event_bus)
        self._service(context).close()

    def save(self, context: ProjectModuleContext) -> None:
        self._representation(context).synchronize()
        self._service(context).save()

    def _service(self, context: ProjectModuleContext) -> InvestigationService:
        service = context.repository.module_repository(self.descriptor.module_id, self.SERVICE_NAME)
        if not isinstance(service, InvestigationService):
            raise RuntimeError("Service Investigation indisponible.")
        return service

    def _representation(self, context: ProjectModuleContext) -> InvestigationPhysicalRepresentationService:
        value = context.repository.module_repository(self.descriptor.module_id, self.PHYSICAL_REPRESENTATION_NAME)
        if not isinstance(value, InvestigationPhysicalRepresentationService):
            raise RuntimeError("Représentation physique Investigation indisponible.")
        return value
