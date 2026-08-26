# Module Investigation — Phase 3 : Relations

Cette phase ajoute les relations sans dépendance à Qt, Timeline, Bookmarks ou DetailsPanel.

`InvestigationTargetRef(target_kind, target_id)` est une référence légère et réutilisable. Une `InvestigationRelation` lie exactement deux références, sans copier les objets sources.

Les types disponibles sont `RELATED_TO`, `CONFIRMS`, `CONTRADICTS`, `DERIVED_FROM`, `DUPLICATES` et `REFERENCES`. La table `RELATION_SEMANTICS` porte leur comportement ; `DUPLICATES` est symétrique et normalisé. Les auto-références sont interdites dans cette phase.

Les relations sont persistées individuellement dans le store primaire `relations`. Les index dérivés et reconstructibles sont :

- `relation_id → InvestigationRelation`
- `source_target → relation_ids`
- `destination_target → relation_ids`
- `relation_type → relation_ids`
- `signature normalisée → relation_id`

API publique : `create_relation`, `update_relation`, `delete_relation`, `get_relation`, `list_relations` et `find_relations_for_target`.

Les affaires, hypothèses, collections, notes, tags, journal, recherche, graphes et vues Qt restent hors périmètre.
