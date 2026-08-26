# Module Investigation — Phase 2 : InvestigationItem

La phase 2 introduit uniquement `InvestigationItem`, l'annotation légère et
typée d'un sujet métier existant.

## Modèle

Un item contient un identifiant stable, `subject_kind`, `subject_id`, un titre
et un résumé facultatifs, une priorité, un statut et ses métadonnées d'auteur
et de dates. Il ne copie jamais les métadonnées, le contenu ou l'aperçu de son
sujet source.

`InvestigationPriority` et `InvestigationStatus` sont des enums. La référence
du sujet est immuable après création ; un unique item peut référencer un couple
`(subject_kind, subject_id)` dans un projet.

## Persistance et index

Les items sont enregistrés individuellement dans le store logique `items`.
Les autres stores Investigation restent uniquement réservés et ne reçoivent
aucune écriture pendant cette phase.

`InvestigationManager` maintient deux index dérivés et reconstructibles :

```text
item_id                   → InvestigationItem
(subject_kind, subject_id) → item_id
```

Le repository est le seul composant qui lit ou écrit le store ; service,
manager et modèle métier restent indépendants de Qt et du backend physique.

## API publique

```text
create_item
update_item
delete_item
get_item
find_item_by_subject
list_items
```

Les opérations sur cases, hypothèses, collections, notes, tags, relations,
journal, recherche et vues restent explicitement hors périmètre.
