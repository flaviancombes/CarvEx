# Audit de performances CarvEx

## Portée et méthode

Cet audit porte sur le chemin d'affichage PySide6 et les services de métadonnées, d'artefacts et de chronologie. Les mesures sont activables avec `CARVEX_PERF=1` ; elles sont désactivées par défaut et n'ont aucun impact volontaire sur l'interface utilisateur.

Le dépôt de travail ne fournit pas d'interpréteur Python exécutable : les gains ci-dessous sont donc des gains structurels attendus. Ils doivent être validés avec un jeu de rapports représentatif (2 000, 100 000 puis 500 000 fichiers).

## Optimisations réalisées

| Zone | Changement | Gain attendu |
| --- | --- | --- |
| Sélection depuis Timeline | Index `id(record) → ligne` dans `FileTable` | Passage de O(n) à O(1) pour la synchronisation normale Timeline → Fichiers. |
| Filtres de fichiers | Aucun `invalidateFilter()` si le critère n'a pas changé | Évite les nouveaux parcours complets déclenchés par des signaux Qt redondants. |
| Timeline globale | Construction coopérative par lots de 32 enregistrements avec `QTimer` | L'event loop conserve la main au lieu de bloquer pendant la création de tous les événements. |
| Timeline globale | Modèle Qt enrichi par `beginInsertRows()` | Évite les `beginResetModel()` complets à chaque lot et conserve la virtualisation native de `QTableView`. |
| Données Timeline | Références aux objets fichiers et événements existants | Pas de copie des enregistrements du rapport entre table, détail et Timeline. |
| Recherche Timeline | Requête normalisée une seule fois et rendu sans tuple intermédiaire par cellule | Réduit les allocations et normalisations répétées dans le proxy et pendant le repaint. |

## Points identifiés

### Interface et modèles Qt

- `QTableView` et `QAbstractTableModel` sont les bons composants : Qt ne matérialise que les cellules visibles. Il ne faut pas les remplacer par une grille de widgets.
- `FileTableModel.set_records()` utilise un seul reset lors du changement de rapport : c'est approprié. Il ne doit pas être appelé lors des filtres, recherches ou sélections.
- Le panneau de détails crée volontairement des widgets de métadonnées lors d'une sélection. Cette opération reste localisée à un seul fichier ; elle ne doit jamais être appliquée à la table entière.
- Le redimensionnement d'aperçu provoque une mise à l'échelle d'image. Un cache de pixmaps redimensionnés serait utile uniquement après profilage, car il augmente fortement la mémoire. Aucun changement n'a été effectué afin de préserver le comportement des aperçus.

### Recherche et filtres

- La recherche `QSortFilterProxyModel` est linéaire par nature : chaque modification de texte parcourt les lignes et normalise jusqu'à six champs. À 500 000 fichiers, elle devra être déclenchée avec un délai court (150–250 ms) ou exécutée dans un index dédié, après mesure.
- Le filtre d'artefacts est le principal risque actuel : il peut demander l'extraction de métadonnées pour les images non encore mises en cache. Il faut conserver son comportement, mais préparer un index d'artefacts asynchrone si son usage devient courant.
- Les filtres ne doivent jamais reconstruire le modèle source ; ils doivent continuer à passer par le proxy existant.

### Caches et mémoire

- Les caches de métadonnées et de timeline sont indispensables pour éviter les réextractions. Ils sont actuellement non bornés : c'est efficace en CPU mais peut devenir coûteux en mémoire avec 500 000 fichiers.
- Avant de borner un cache, mesurer la taille moyenne des résultats. Une politique LRU configurable, avec conservation des éléments visibles/sélectionnés, est recommandée si la mémoire dépasse le budget cible.
- La Timeline conserve une unique collection d'événements centrale ; les modèles et vues ne reconstituent pas ces événements.

## Instrumentation développeur

Lancer CarvEx avec `CARVEX_PERF=1`. Le logger `carvex.performance` écrit :

- durée et allocations Python approximatives des lots de Timeline ;
- durée d'ouverture du rapport et de rattachement des données à l'interface ;
- taille des caches de métadonnées et de timeline via `utils.performance.log_cache_sizes(...)` ;
- points d'instrumentation futurs sans dépendance Qt.

Les mesures `tracemalloc` représentent la mémoire Python, pas la mémoire native de Qt/Pillow. Pour une mesure de processus complète sous Windows, compléter ultérieurement par un outil externe ou `psutil` optionnel.

## Recommandations avant 100 000–500 000 fichiers

1. Mesurer avec des rapports réalistes et fixer un budget mémoire explicite.
2. Déplacer les extractions de métadonnées/artefacts globales vers des tâches de fond avec annulation et progression, avant d'ajouter de nouveaux extracteurs lourds.
3. Ajouter une persistance d'index (SQLite ou fichier d'index) pour éviter de reconstruire la Timeline après chaque lancement sur les très gros projets.
4. Ajouter un index de recherche dédié seulement après profilage ; éviter de dupliquer toutes les chaînes par défaut.
5. Prévoir un contrôleur de sélection partagé qui transmet l'objet fichier/événement au même `DetailsPanel`, plutôt que de dupliquer les panneaux dans les futures vues Investigation.
6. Tester explicitement les erreurs/corruptions et les annulations durant la construction par lots.
