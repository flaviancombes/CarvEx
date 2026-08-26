# Filtrage des artefacts et performances

`FileFilterProxyModel.filterAcceptsRow()` ne calcule jamais de métadonnée,
d'artefact ou d'événement Timeline. Lorsqu'un filtre Artefacts est actif, il
lit exclusivement `ArtifactClassifier.cached_for()` ; une entrée absente ne
correspond pas au filtre pendant son préchargement.

`ArtifactPreloader` est déclenché par la vue Fichiers, jamais par le proxy.
Il parcourt les seules images dans un `QRunnable`, par lots, et notifie l'UI
lorsque de nouveaux résultats sont en cache. L'UI invalide alors le filtre,
sans extraire quoi que ce soit.

La Timeline n'extrait pas de données depuis son `TimelineFilterProxyModel` :
il ne consulte que les `TimelineEvent` déjà présents dans son modèle.
