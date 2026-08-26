# Chaîne de conservation du rapport source

Chaque projet conserve un `ReportSourceSnapshot` pour le rapport PhotoRec qui
alimente ses preuves. Le snapshot comprend l'empreinte SHA-256 du fichier de
rapport, sa taille, sa date, sa version déclarée, son nombre de fichiers et une
empreinte d'inventaire calculée à partir des `file_id` canoniques triés.

L'empreinte d'inventaire est indépendante de l'ordre d'affichage du rapport.
Ainsi, un rapport réordonné ou dont seule la présentation change est détecté,
mais ne peut pas déplacer une référence vers une autre preuve. À l'inverse,
l'ajout, la suppression, ou le remplacement d'une preuve modifie l'inventaire
et exige une confirmation explicite avant chargement.

À l'ouverture :

- rapport manquant : l'utilisateur peut le localiser ou ouvrir explicitement
  le projet sans corpus ;
- rapport illisible : le corpus n'est pas chargé ;
- inventaire différent : avertissement bloquant avec comparaison des
  empreintes, avant toute adoption ;
- même inventaire depuis un autre emplacement : avertissement explicite ;
- même inventaire mais rapport brut différent : message de statut indiquant
  un réordonnancement ou une modification de présentation sans impact sur les
  preuves.

Chaque rattachement initial, relocalisation et remplacement accepté ajoute une
entrée synthétique immutable à `ProjectMetadata.source_audit`. Elle conserve
les références, les empreintes avant/après et un résumé, sans copier le corpus.

Les projets historiques sans empreinte d'inventaire sont traités de manière
conservatrice : seule l'égalité du rapport brut est considérée comme sûre. Le
premier rattachement validé crée le snapshot moderne.

Limite : une empreinte établit l'intégrité du rapport CarvEx chargé ; elle ne
certifie pas l'origine physique du média PhotoRec ni l'horodatage d'acquisition
externe. Ces éléments doivent être conservés dans la procédure DFIR adjacente.
