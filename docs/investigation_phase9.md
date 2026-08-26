# Module Investigation — Phase 9 : Evénements métier

Les événements Investigation sont des objets métier immuables, horodatés et
indépendants de Qt, de l'interface et du stockage. `DomainEvent` fournit
l'identifiant et l'horodatage ; `InvestigationEvent` ajoute un `EventType`,
l'identifiant minimal de l'entité et, si nécessaire, des `InvestigationTargetRef`.
Il ne contient jamais une copie d'objet Investigation ou DFIR.

Cycle de vie :

```text
InvestigationService → InvestigationManager (opération réussie) → EventBus.publish
                                                              ↓
                                                     subscribers synchrones
```

Les repositories ne publient jamais d'événements et le Manager ne connaît ni le
bus ni les abonnés. Le Service publie seulement après que l'opération métier a
réussi.

`EventBus` gère l'abonnement, le désabonnement et une diffusion synchrone dans
l'ordre des abonnements. Un abonnement peut filtrer les `EventType`. Le bus ne
persiste rien et n'utilise aucune file asynchrone.

Bonnes pratiques pour les modules futurs : publier via un `EventPublisher`,
s'abonner avec un composant explicitement désabonné lors de sa fermeture, ne pas
effectuer d'opération lente dans un subscriber, et ne jamais faire publier un
repository ou une vue Qt.

Le Journal, la Recherche, les modèles Qt et les vues Investigation restent hors
périmètre.
