# Module Investigation — première vue Qt

La première interface Investigation respecte la séparation MVC existante :

- `InvestigationTreeModel` (dans la couche `models`) est un modèle Qt passif à deux niveaux ; il ne
  connaît ni service, ni repository ;
- `InvestigationTreeView` ne transmet que les expansions et sélections ;
- `InvestigationController` compose `InvestigationService`,
  `InvestigationQueryService` et `InvestigationIntegrityValidator` ;
- `InvestigationPanel` assemble la présentation, l'avertissement d'intégrité
  non bloquant et la consultation du diagnostic.

Les six sections (`Cases`, `Collections`, `Hypothèses`, `Notes`, `Tags`,
`Journal`) sont créées immédiatement, mais leurs enfants sont chargés à la
première expansion. Lorsqu'un `InvestigationEvent` est publié, le contrôleur
rafraîchit uniquement la section déjà chargée concernée ; le Journal déjà
chargé est également rafraîchi. Aucune vue n'accède à un repository et aucun
index du domaine n'est reconstruit.

Lors d'une sélection, le contrôleur demande le contexte approprié au
`InvestigationQueryService`, puis publie un `SelectionContext` léger vers le
`SelectionManager`. Le `DetailsPanel` partagé continue donc de recevoir la
sélection via son mécanisme existant ; lorsqu'une Note ou une entrée de Journal
référence un fichier, son identifiant est transmis comme relation légère afin
de conserver l'aperçu de fichier existant.

Le validateur est exécuté à l'attachement de la vue, donc à l'ouverture d'un
projet. Ses anomalies n'empêchent jamais l'ouverture : elles sont signalées
dans une bannière discrète et consultables à la demande.
