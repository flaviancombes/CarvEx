# Module Investigation — Phase 5 : Tags

Cette phase ajoute le catalogue global `InvestigationTag` et les associations indépendantes `TagAssignment`. Les tags ne sont jamais embarqués dans `InvestigationItem`.

Un tag possède un nom affiché et un nom normalisé unique dans le projet. Les assignations utilisent uniquement `InvestigationTargetRef` et garantissent l'unicité du couple `(tag_id, target_ref)`.

Les données primaires sont persistées dans `tags` et `tag_assignments`. Les index reconstruisibles sont :

- `tag_id → InvestigationTag`
- `normalized_name → tag_id`
- `target_ref → tag_ids`
- `tag_id → target_refs`

Les stores sont des namespaces logiques : ils sont initialisés par le module à
l'ouverture, même lorsqu'un projet créé avant cette phase ne possède encore
aucune donnée ou namespace `tag_assignments`.

Le compteur d'utilisation est dérivé de `tag_id → target_refs` ; il n'est ni stocké ni sérialisé dans un tag.

API publique : `create_tag`, `update_tag`, `delete_tag`, `get_tag`, `list_tags`, `assign_tag`, `unassign_tag`, `find_tags_for_target`, `find_targets_for_tag` et `tag_usage_count`.

Collections, hypothèses, affaires, journal, recherche et vues Qt restent hors périmètre.
