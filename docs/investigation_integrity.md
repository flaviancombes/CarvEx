# Module Investigation — validation d'intégrité

`InvestigationIntegrityValidator` produit un diagnostic immuable de cohérence
du domaine. Il consomme uniquement les APIs de lecture d'`InvestigationService` :
il n'accède jamais aux repositories, ne reconstruit aucun index, ne modifie
aucune donnée et ne publie aucun événement.

Le module en enregistre une instance par défaut sous le nom
`integrity_validator`. Une orchestration qui connaît les modules externes peut
instancier le même validateur avec un résolveur de références adapté.

Le rapport contient des `IntegrityIssue` typés (`INFO`, `WARNING`, `ERROR`) et
une `IntegrityReport`. Les contrôles couvrent les sujets des Items, les
relations, les memberships d'affaires, collections et hypothèses, les notes,
les assignations de tags et les cibles du Journal. Les relations symétriques
sont normalisées pour détecter les doublons logiques et les auto-références
interdites sont signalées.

## Références externes

Investigation référence des objets appartenant à d'autres modules sans les
importer. Le validateur accepte donc un résolveur optionnel
`Callable[[InvestigationTargetRef], bool | None]`. `False` signale une cible
orpheline ; `True` la confirme ; `None` indique qu'elle est hors de son
périmètre. Sans résolveur, les types Investigation connus (`case`,
`collection`, `hypothesis`, `note`, `tag`, `relation`, `item`) sont vérifiés
via les APIs publiques du domaine, tandis que les références externes restent
neutres.

## Extension

Un futur module ajoute ses contrôles dans une méthode de validation dédiée, sans
modifier les données primaires. Il peut fournir son propre résolveur de cibles
externes ou composer plusieurs résolveurs dans la couche d'orchestration. Toute
nouvelle règle doit produire un code stable, une gravité et une cible lorsque
celle-ci est disponible.
