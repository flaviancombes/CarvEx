# Opérations de masse

`core.batch.BatchOperationResult` est le contrat générique des commandes de
masse. Il est indépendant de Qt, du stockage et de tout module métier. Une
commande retourne le nombre demandé, les objets effectivement appliqués, ceux
ignorés et un identifiant d'opération.

## Investigation

`InvestigationService.create_items_batch()` crée les preuves absentes pour un
ensemble de `InvestigationTargetRef`. Les sujets déjà présents ou répétés sont
ignorés. `add_files_to_collection_batch()` crée les preuves fichier manquantes
puis les rattache à une Collection dans une même commande métier.

Les contrôles d'unicité sont effectués avant toute écriture. Les écritures d'un
store sont compensées si une écriture ultérieure échoue. Pour le rattachement à
une Collection, les nouvelles preuves sont également supprimées si les
memberships ne peuvent pas être créés ; une preuve déjà existante n'est jamais
supprimée. Les événements sont publiés seulement après que les index mémoire et
la persistance sont cohérents.

Chaque commande publie un unique événement `BATCH_COMPLETED`. L'arbre
Investigation conserve son chargement paresseux : une section non ouverte n'est
pas matérialisée par l'événement. La table Fichiers notifie uniquement sa colonne
d'indicateur, avec un nombre borné de signaux `dataChanged` pour les très grands
lots et sans `modelReset`.

## Complexité

La déduplication, les validations et les index utilisent des dictionnaires et
des ensembles : le coût est `O(n)` en temps et `O(n)` temporaire pour un lot de
`n` cibles. Aucun parcours quadratique ni événement par fichier n'est effectué.
Les index persistés restent inexistants : ils sont toujours reconstruits depuis
les données primaires à l'ouverture du projet.

## Réutilisation

Les futurs modules peuvent réutiliser `BatchOperationResult` et appliquer la
même discipline : validation complète, écriture compensée si le backend ne
propose pas de transaction, mise à jour des index, puis une seule notification
de finalisation. Les opérations unitaires restent disponibles pour les actions
ponctuelles.
