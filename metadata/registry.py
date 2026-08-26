"""Registre ordonné des providers de métadonnées.

Le registre est le seul point d'extension du pipeline : ajouter un format ne
nécessite aucune modification du manager ni de l'interface.
"""

from __future__ import annotations

from collections.abc import Iterable

from metadata.base import FileRecord, MetadataProvider


class MetadataProviderRegistry:
    """Conserve les providers dans un ordre stable, par priorité décroissante."""

    def __init__(self, providers: Iterable[MetadataProvider] = ()) -> None:
        self._providers: list[MetadataProvider] = []
        for provider in providers:
            self.register(provider)

    def register(self, provider: MetadataProvider) -> None:
        """Enregistre un provider avec un identifiant unique."""
        if any(item.provider_id == provider.provider_id for item in self._providers):
            raise ValueError(f"Le provider de métadonnées {provider.provider_id!r} est déjà enregistré.")
        self._providers.append(provider)
        self._providers.sort(key=lambda item: item.priority, reverse=True)

    def providers_for(self, file_record: FileRecord) -> tuple[MetadataProvider, ...]:
        """Retourne tous les providers compatibles, sans connaître les formats."""
        return tuple(provider for provider in self._providers if provider.supports(file_record))

    @property
    def providers(self) -> tuple[MetadataProvider, ...]:
        return tuple(self._providers)
