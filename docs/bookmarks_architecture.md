# Architecture du module Bookmarks

## Source de vérité

`BookmarkService` est l'unique propriétaire de l'état. Il conserve un index `BookmarkKey(subject_kind, subject_id) → Bookmark`, ce qui rend `contains()` constant en temps et indépendant des vues Qt.

Les objets bookmarkés sont génériques : fichier, événement Timeline, résultat YARA, entrée Registry ou tout futur sujet métier. Un bookmark ne copie jamais les données de son sujet.

## Composants

| Composant | Responsabilité |
| --- | --- |
| `Bookmark` / `BookmarkKey` | Référence métier typée et extensible : note, tags, couleur, priorité, collection, auteur et dates. |
| `BookmarkRepository` | Contrat de persistance remplaçable. |
| `InMemoryBookmarkRepository` | Stockage initial, sans dépendance UI. |
| `BookmarkService` | Ajout, retrait, bascule, opérations en lot, statistiques et diffusion des changements. |
| `BookmarkModel` | Projection Qt passive des bookmarks du service. |
| `BookmarkStarDelegate` | Étoile cliquable virtualisée, sans widget par ligne. |
| `BookmarksView` | Vue `QTableView` des références bookmarkées. |
| `BookmarkSubjectResolverRegistry` | Conversion extensible d'un bookmark vers le `SelectionContext` de son sujet. |

## Synchronisation

```text
Delegate / vue → BookmarkService → bookmarks_changed(keys)
                                  ├─ FileTableModel.dataChanged ciblé
                                  ├─ TimelineTableModel.dataChanged ciblé
                                  └─ BookmarkModel insert/remove ciblé
```

Les vues ne se synchronisent pas entre elles et ne possèdent aucun état de bookmark.

## Sélection

`BookmarksView` émet le bookmark sélectionné. `MainWindow` publie ensuite le même `SelectionContext` métier que les vues Fichiers ou Timeline. Le `DetailsPanel` partagé ne contient aucune logique spécifique aux bookmarks.

## Persistance et extensions

Le service dépend uniquement du contrat `BookmarkRepository`. Les implémentations JSON, SQLite et `.carvex` pourront être ajoutées sans toucher au service, aux modèles ou aux vues.

Les opérations `add_many`, `remove_many` et `toggle_many` publient un résultat de lot unique. Les méthodes `count`, `count_by_kind`, `count_by_priority`, `count_by_collection` et `count_by_tag` préparent les statistiques et filtres futurs.
