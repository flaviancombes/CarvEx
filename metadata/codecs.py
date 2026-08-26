"""Codecs déclarés par le module Metadata, jamais par le stockage central."""

from project.codecs import ProjectCodecRegistry, dataclass_codec, enum_codec


def register_metadata_codecs(registry: ProjectCodecRegistry) -> None:
    from metadata.base import MetadataCategory, MetadataConfidence, MetadataField, MetadataValueType
    from metadata.correlation import MetadataCorrelation, MetadataCorrelationType
    from metadata.indexing import MetadataIndexingCheckpoint, MetadataIndexingEntry, MetadataIndexingState

    registry.register_many(
        [
            dataclass_codec("dataclass:metadata.base.MetadataField", MetadataField),
            enum_codec("enum:metadata.base.MetadataCategory", MetadataCategory),
            enum_codec("enum:metadata.base.MetadataConfidence", MetadataConfidence),
            enum_codec("enum:metadata.base.MetadataValueType", MetadataValueType),
            dataclass_codec("dataclass:metadata.indexing.MetadataIndexingEntry", MetadataIndexingEntry),
            dataclass_codec("dataclass:metadata.indexing.MetadataIndexingCheckpoint", MetadataIndexingCheckpoint),
            enum_codec("enum:metadata.indexing.MetadataIndexingState", MetadataIndexingState),
            dataclass_codec("dataclass:metadata.correlation.MetadataCorrelation", MetadataCorrelation),
            enum_codec("enum:metadata.correlation.MetadataCorrelationType", MetadataCorrelationType),
        ]
    )
