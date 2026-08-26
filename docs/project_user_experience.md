# Expérience utilisateur des projets

`MainWindow` orchestre uniquement Qt : elle appelle `ProjectManager`, rattache
les services spécialisés au projet actif et reflète cet état dans le titre, la
barre d'état et l'écran d'accueil. Elle n'accède jamais au stockage.

| Composant | Responsabilité |
| --- | --- |
| `ProjectHome` | Accueil sans projet, accès aux actions principales et aux projets récents. |
| `NewProjectDialog` | Collecte le nom, l'emplacement, la description et une importation PhotoRec facultative. |
| `MainWindow` | Dialogues, confirmation de fermeture et synchronisation UI des services déjà existants. |
| `Workspace` | Mémorise onglet, splitter, colonnes, tri, filtres et recherches sans rendre les données d'investigation modifiées. |

`BookmarkService` reste la source de vérité des favoris. Lors d'un changement
de projet, il est simplement rattaché au repository fourni par le module
Bookmarks ; ses modèles Qt reçoivent une notification ciblée.

`JsonProjectStorage` est un adapter local de convenance. Son fichier
`project.json` n'est pas le format logique `.carvex` et peut être remplacé par
un adapter SQLite ou hybride sans modifier les vues ni les services métier.
