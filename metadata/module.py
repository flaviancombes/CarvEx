"""Intégration déclarative du store Metadata au système de projets."""

from metadata.codecs import register_metadata_codecs
from metadata.correlation import MetadataCorrelationEngine, MetadataCorrelationStore
from metadata.indexing import MetadataIndexingService
from metadata.manager import MetadataManager
from metadata.store import MetadataStore
from project.modules import ModuleDescriptor, ProjectModule, ProjectModuleContext


class MetadataProjectModule(ProjectModule):
    def __init__(self, manager: MetadataManager) -> None:
        self._manager = manager

    @property
    def descriptor(self) -> ModuleDescriptor:
        return ModuleDescriptor(
            module_id="metadata",
            schema_version=1,
            capabilities_provided=frozenset({"metadata-store"}),
            store_names=frozenset({"fields", "index", "correlations", "correlation_index"}),
        )

    def register_codecs(self, registry) -> None:
        register_metadata_codecs(registry)

    def initialize(self, context: ProjectModuleContext) -> None:
        store = MetadataStore(context.store("fields"), context.store("index"))
        indexing = MetadataIndexingService.from_checkpoint(store.load_checkpoint(), store.known_file_ids())
        indexing.normalize_interrupted_states()
        correlation_store = MetadataCorrelationStore(context.store("correlations"), context.store("correlation_index"))
        correlation_engine = MetadataCorrelationEngine(store, store.index)
        context.register_repository("store", store)
        context.register_repository("indexing_service", indexing)
        context.register_repository("correlation_store", correlation_store)
        context.register_repository("correlation_engine", correlation_engine)

    def open(self, context: ProjectModuleContext) -> None:
        self._manager.attach_store(context.repository.module_repository("metadata", "store"))

    def close(self, context: ProjectModuleContext) -> None:
        self._manager.detach_store()
