# Module Investigation — Phase 11 : couche de requêtes

`InvestigationQueryService` est une façade de lecture qui compose les APIs
publiques d'`InvestigationService`. Il ne dépend ni de Qt, ni des repositories,
ni du stockage physique ; il ne modifie aucune donnée et ne publie aucun
événement.

Les projections typées disponibles sont :

- `InvestigationTargetContext` : Item, notes, tags, relations, collections,
  affaires, hypothèses et journal associés directement à une cible ;
- `InvestigationCaseContext` : membres et annotations directement portées par
  l'affaire ;
- `InvestigationCollectionContext` : membres, notes et tags directement portés
  par la collection ;
- `InvestigationHypothesisContext` : memberships avec leurs rôles typés et
  relations directement portées par l'hypothèse.

Une projection ne traverse jamais implicitement les membres d'une affaire, d'une
collection ou d'une hypothèse. Cette règle évite les parcours de graphe coûteux
et laisse aux futurs écrans, rapports et exports le contrôle explicite de leur
périmètre.

La façade est créée par `InvestigationProjectModule` et enregistrée sous le nom
`query_service`. Elle emploie exclusivement les index déjà maintenus par
`InvestigationManager`; elle ne les reconstruit jamais.

## Commandes et requêtes

`InvestigationService` reste la façade des commandes : création, modification,
suppression et publication d'événements. `InvestigationQueryService` est sa
contrepartie de lecture : projections sans effet de bord. Les futures vues Qt,
le DetailsPanel, la recherche, les rapports et les exports doivent consommer
cette couche ou des services de requêtes spécialisés, jamais les repositories.
