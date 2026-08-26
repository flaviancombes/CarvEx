# Module Investigation — Phase 1

La première phase installe uniquement l'infrastructure du module Investigation.
Elle ne crée aucune entité d'enquête et ne fournit aucune vue Qt.

## Composants

| Composant | Responsabilité |
| --- | --- |
| `InvestigationProjectModule` | Déclare la capability, les stores et le cycle de vie auprès du système de projets. |
| `InvestigationRepository` | Encapsule les stores logiques Investigation ; il ne connaît aucun backend physique. |
| `InvestigationManager` | Porte l'état ouvert/fermé du module et accueillera les futurs agrégats. |
| `InvestigationService` | Façade applicative unique des futures commandes Investigation. |

## Cycle de vie

```text
ProjectManager.create/open
  → InvestigationProjectModule.initialize
  → InvestigationRepository + InvestigationManager + InvestigationService
  → InvestigationProjectModule.open
  → InvestigationService.open

ProjectManager.save
  → InvestigationProjectModule.save
  → ProjectRepository.flush

ProjectManager.close
  → InvestigationProjectModule.close
  → InvestigationService.close
  → ProjectRepository.flush
```

La sauvegarde reste centralisée par `ProjectManager` et `ProjectRepository`.
Le module ne lit ni n'écrit de fichier et ne contient pas de cache à synchroniser
durant cette phase.

## Stores réservés

Le module déclare les stores primaires prévus : `items`, `collections`, `notes`,
`tags`, `relations`, `hypotheses`, `hypothesis_memberships`, `cases`,
`case_memberships` et `journal`.

Cette déclaration ne constitue pas une implémentation de ces entités : aucun
store n'est écrit avant les phases qui introduiront leurs modèles métier.
