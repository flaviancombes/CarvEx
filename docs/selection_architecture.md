# Architecture de sélection partagée

## Responsabilités

- `SelectionContext` est immuable et léger : type, identifiant métier, origine et relations par identifiants. Il ne contient jamais de métadonnées, aperçu, artefact ou résultat d'analyse.
- `SelectionManager` est le bus de sélection local de l'application. Il publie les contextes, conserve un historique borné et ne dépend d'aucun service métier ou widget d'affichage.
- `FileSelectionRegistry` conserve des références aux fichiers déjà connus et résout paresseusement les autres références du rapport.
- `FileSelectionResolver` transforme un contexte léger en référence de fichier lorsque le consommateur en a besoin.
- `DetailsPanel` reste un consommateur. Il affiche les données via ses services existants après résolution du fichier ; il ne reçoit pas de données métier depuis une vue.

## Flux

```text
Vue Qt → SelectionContext léger → SelectionManager → abonnés
                                                  ├─ DetailsPanel → services existants
                                                  ├─ Hex Viewer futur
                                                  ├─ Graph futur
                                                  └─ Investigation future
```

## Historique

L'historique est interne à `SelectionManager`, borné à 100 contextes par défaut, navigable par `go_back()` et `go_forward()`. Il peut être exposé plus tard sans changer les vues.

## Extension

Un module futur publie uniquement un nouveau `subject_kind` et ses identifiants liés. Il peut fournir son propre résolveur ou des fournisseurs de sections du panneau, sans modifier le gestionnaire de sélection.
