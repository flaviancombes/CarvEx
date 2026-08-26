# Module Investigation — Phase 7 : Collections

`InvestigationCollection` est un regroupement logique autonome. Elle ne copie
jamais les objets qu'elle organise et ne dépend ni des Cases, ni des modules DFIR,
ni de Qt.

Les associations `CollectionMembership` sont des données primaires persistées
dans `collection_memberships`, distinctes des Collections dans `collections`. Elles
ne contiennent qu'un identifiant de collection et une `InvestigationTargetRef`.

Le schéma du module Investigation passe à la version 2. La migration `1 → 2`
déclare les deux stores logiques de Collections sans écrire de donnée primaire ;
les projets antérieurs restent donc ouvrables et leur manifest est mis à jour.

Les index reconstruisibles sont :

- `collection_id → InvestigationCollection`
- `target_ref → collection_ids`
- `collection_id → target_refs`

L'unicité du couple `(collection_id, target_ref)` est garantie par
`InvestigationManager`. La suppression d'une Collection supprime uniquement ses
memberships, jamais les objets référencés.

API publique : `create_collection`, `update_collection`, `delete_collection`,
`get_collection`, `list_collections`, `add_to_collection`,
`remove_from_collection`, `find_collection_members` et
`find_collections_for_target`.

Les Hypothèses, le Journal, la Recherche, les modèles Qt et toute vue
Investigation restent hors périmètre de cette phase.
