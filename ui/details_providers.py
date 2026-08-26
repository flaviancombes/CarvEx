"""Points d'extension de contenu pour le DetailsPanel partagé."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from selection.context import SelectionContext
from selection.resolver import SelectionResolver


class DetailsPanelHost(Protocol):
    """Contrat explicite offert par le panneau partagé à ses providers."""

    def set_file(self, file_record: Mapping[str, Any] | None) -> None: ...

    def clear_provider_widget(self) -> None: ...

    def show_provider_widget(self, title: str, widget: Any) -> None: ...

    def populate_file_context(self, context: SelectionContext) -> bool: ...

    def show_file_extension_widget(self, widget: Any) -> None: ...

    def current_file_title(self) -> str: ...

    def publish_context(self, context: SelectionContext) -> None: ...

    def widget(self) -> Any: ...


class DetailsProvider(Protocol):
    """Fournit le rendu d'un type de sélection, sans connaître les vues Qt source."""

    def supports(self, context: SelectionContext) -> bool: ...

    def populate(self, panel: DetailsPanelHost, context: SelectionContext) -> None: ...


class DetailsProviderRegistry:
    """Résout le provider le plus récemment enregistré pour une sélection."""

    def __init__(self) -> None:
        self._providers: list[DetailsProvider] = []

    def register(self, provider: DetailsProvider) -> None:
        if provider not in self._providers:
            self._providers.append(provider)

    def clear(self) -> None:
        self._providers.clear()

    def unregister(self, provider: DetailsProvider) -> None:
        if provider in self._providers:
            self._providers.remove(provider)

    def populate(self, panel: DetailsPanelHost, context: SelectionContext) -> bool:
        for provider in reversed(self._providers):
            if provider.supports(context):
                provider.populate(panel, context)
                return True
        return False


class FileDetailsProvider:
    """Adapter de compatibilité du rendu historique des fichiers et événements liés."""

    def __init__(self, resolver: SelectionResolver) -> None:
        self._resolver = resolver

    def supports(self, context: SelectionContext) -> bool:
        return self._resolver.resolve_file(context) is not None

    def populate(self, panel: DetailsPanelHost, context: SelectionContext) -> None:
        file_record: Mapping[str, Any] | None = self._resolver.resolve_file(context)
        panel.set_file(file_record)
