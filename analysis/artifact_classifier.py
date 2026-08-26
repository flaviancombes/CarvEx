"""Orchestrateur et cache des règles d'artefacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from threading import RLock

from analysis.artifact import Artifact
from analysis.rules import DEFAULT_RULES, ArtifactRule
from metadata.base import MetadataResult
from metadata.cache import MetadataCache


class ArtifactClassifier:
    """Évalue un registre de règles, une seule fois par résultat de métadonnées."""

    def __init__(self, rules: Iterable[ArtifactRule]) -> None:
        self._rules = tuple(rules)
        self._cache: dict[str, tuple[Artifact, ...]] = {}
        self._lock = RLock()

    def cached_for(self, file_record: Mapping[str, object]) -> tuple[Artifact, ...] | None:
        """Retourne uniquement un résultat déjà calculé, sans extraction."""
        with self._lock:
            return self._cache.get(MetadataCache.key_for(file_record))

    def classify(self, file_record: Mapping[str, object], metadata: MetadataResult) -> tuple[Artifact, ...]:
        key = MetadataCache.key_for(file_record)
        cached = self.cached_for(file_record)
        if cached is not None:
            return cached
        artifacts = tuple(artifact for rule in self._rules for artifact in rule.evaluate(file_record, metadata))
        with self._lock:
            # Un autre consommateur peut avoir rempli le cache pendant l'évaluation.
            return self._cache.setdefault(key, artifacts)

    def clear(self) -> None:
        """Release project-scoped classification results when the report changes."""
        with self._lock:
            self._cache.clear()


def build_default_classifier() -> ArtifactClassifier:
    return ArtifactClassifier(DEFAULT_RULES)
