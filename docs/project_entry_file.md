# Fichier d'entrée de projet

Chaque projet CarvEx possède un fichier `project.carvex` à sa racine. C'est le
point d'entrée stable destiné à l'ouverture depuis l'interface et, plus tard,
à l'association Windows `.carvex`.

Son format JSON actuel est volontairement minimal : il déclare sa version et
le backend contenant les stores (`project.json`). Les données métier restent
exclusivement dans les repositories et stores existants.

`JsonProjectStorage` accepte le dossier projet ou le fichier `project.carvex`.
Lorsqu'un projet historique contient seulement `project.json`, son premier
chargement crée silencieusement le fichier d'entrée, sans migration des données
du projet.
