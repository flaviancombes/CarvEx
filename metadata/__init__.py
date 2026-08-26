"""Framework extensible d'extraction de métadonnées CarvEx."""

from metadata.base import MetadataCategory, MetadataConfidence, MetadataField, MetadataValueType
from metadata.correlation import (
    MetadataCorrelation,
    MetadataCorrelationEngine,
    MetadataCorrelationIndex,
    MetadataCorrelationStore,
    MetadataCorrelationType,
)
from metadata.manager import MetadataManager, build_default_manager
from metadata.module import MetadataProjectModule
from metadata.query import MetadataFilter, MetadataPredicate, MetadataQuery
from metadata.registry import MetadataProviderRegistry

__all__ = (
    "MetadataCategory",
    "MetadataConfidence",
    "MetadataCorrelation",
    "MetadataCorrelationEngine",
    "MetadataCorrelationIndex",
    "MetadataCorrelationStore",
    "MetadataCorrelationType",
    "MetadataField",
    "MetadataFilter",
    "MetadataManager",
    "MetadataPredicate",
    "MetadataProjectModule",
    "MetadataProviderRegistry",
    "MetadataQuery",
    "MetadataValueType",
    "build_default_manager",
)
