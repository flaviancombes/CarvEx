"""Classification d'artefacts DFIR indépendante de l'interface."""

from analysis.artifact import Artifact
from analysis.artifact_classifier import ArtifactClassifier, build_default_classifier

__all__ = ("Artifact", "ArtifactClassifier", "build_default_classifier")
