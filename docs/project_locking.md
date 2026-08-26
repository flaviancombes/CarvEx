# Verrou exclusif des projets

CarvEx protège chaque projet ouvert par le dossier `.carvex.lock`, créé de
manière atomique dans la racine du projet avant toute lecture ou écriture
persistante. Le verrou couvre donc `project.json`, ses sauvegardes et checksums,
les stores de modules, les workspaces et la représentation physique
Investigation.

Le fichier `owner.json` décrit l'hôte, le PID, la date d'acquisition et un jeton
aléatoire du détenteur. Une seconde instance reçoit une erreur explicite et ne
peut pas ouvrir le projet en écriture.

## Récupération après crash

Après une fermeture brutale, le dossier peut rester présent. Au prochain essai,
CarvEx le récupère seulement lorsque les métadonnées sont valides, que le nom
d'hôte est local et que le PID propriétaire n'existe plus. Les métadonnées
invalides ou un verrou provenant d'un autre hôte ne sont jamais supprimés
automatiquement : une intervention manuelle est requise afin d'éviter de voler
un verrou actif.

La fermeture normale libère le verrou après la fermeture des modules et le
flush final du projet.
