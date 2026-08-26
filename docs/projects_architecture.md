# Architecture des projets CarvEx

## Projet logique

`.carvex` désigne un projet logique. Les services ne manipulent jamais un chemin, fichier JSON, archive ou table SQLite : ils passent par `ProjectRepository`, ses stores et ses repositories de module. Le backend mémoire actuel est une première implémentation de `ProjectStorageAdapter` ; JSON, SQLite et hybride peuvent adopter le même contrat.

## Composants

| Composant | Responsabilité |
| --- | --- |
| `ProjectManager` | Unique point d'accès au projet actif et à son cycle de vie. |
| `Project` | Agrégat logique : manifest, métadonnées, settings, state, workspaces et repository. |
| `ProjectManifest` | Version, compatibilité, capabilities, modules activés et fermeture propre. |
| `ProjectRepository` | Seul accès aux stores et au storage adapter. |
| `ProjectModuleRegistry` | Registre déclaratif de modules autonomes. |
| `ProjectModule` | Déclare schema, capabilities, stores, caches et hooks de cycle de vie. |
| `Workspace` | Disposition UI restaurable, distincte de l'état métier `ProjectState`. |
| `WorkspaceManager` | Active et sauvegarde les workspaces sans dépendre des vues Qt. |
| `ProjectMigrationService` | Registre de migrations logiques versionnées. |
| `ProjectCodecRegistry` | Registre de codecs : le stockage ne connaît aucun type métier de module. |

## Cycle de vie

```text
ProjectManager → manifest minimal → repositories/stores → modules initialize/open
                    │                                      │
                    └──── capabilities et compatibilité ────┘
```

À la fermeture, les modules sont fermés dans l'ordre inverse, puis le manifest est marqué `clean_shutdown`.

## Modules et capabilities

Le manager ne connaît aucun module concret. Un module déclare un `ModuleDescriptor` avec son identifiant, schéma, dépendances, capabilities et stores. `BookmarksProjectModule` est le premier exemple : il fournit la capability `bookmarks` et un `BookmarkRepository` basé sur un store de projet.

## Chargement et performances

L'ouverture charge manifest, métadonnées, settings, état et workspaces uniquement. Les caches, index et résultats de modules restent différés. Les stores permettent de remplacer ensuite le backend mémoire par des accès paginés SQLite sans modifier les services métier.

## Codecs de persistance

`project.storage` encode uniquement des primitives, conteneurs, dates et paires
`type_id` / charge. Il ne contient aucun import vers Investigation, Bookmarks ou
un module optionnel. Au démarrage, `ProjectManager` crée le registre des codecs
du noyau puis appelle `register_codecs()` pour chaque module enregistré, avant la
première lecture du backend JSON.

Pour ajouter une entité persistée, le module crée un `ProjectCodec` (les
fabriques `dataclass_codec` et `enum_codec` couvrent les cas usuels) et l'enregistre
dans `register_codecs()`. Le stockage central ne doit jamais être modifié.

## Migrations modulaires

Le manifest porte une version globale et une version par module. À l'ouverture,
le manager exécute d'abord les migrations globales, puis les migrations des
modules activés dans l'ordre de leurs dépendances. Chaque `ProjectModule` expose
`migrations()` et déclare les transitions `n -> n + 1` dans un
`ModuleMigrationService`.

Une migration reçoit uniquement son `ProjectModuleContext` : elle peut créer ou
transformer ses stores, sans connaître le backend physique ni les autres modules.
Après chaque séquence réussie, la version du module et `migration_history` sont
persistées dans le manifest. Les steps doivent être idempotents : une ouverture
ultérieure ne les réexécute pas car la version cible est déjà enregistrée.
Un ancien manifest ne portant pas encore une version de module reçoit la version
courante comme baseline compatible ; il reste donc ouvrable sans action utilisateur.

## Integrite et recuperation JSON

Le backend JSON conserve le format existant dans `project.json`. A chaque
sauvegarde, il ecrit d'abord une sauvegarde valide `project.json.bak`, puis
publie le nouveau document avec un remplacement atomique. Les fichiers
`project.json.sha256` et `project.json.bak.sha256` contiennent les empreintes
SHA-256 des deux documents.

A l'ouverture, le backend valide la syntaxe JSON, la racine du document et,
lorsqu'elle existe, l'empreinte. Si le document principal est incomplet ou ne
correspond pas a son checksum, la sauvegarde precedente est validee puis
restauree atomiquement. Si aucune version valide n'existe, l'ouverture echoue
explicitement avec une erreur de corruption ; aucun store ni module n'est alors
charge. Les projets historiques sans checksum restent lisibles et recoivent ces
protections a leur prochaine sauvegarde.
