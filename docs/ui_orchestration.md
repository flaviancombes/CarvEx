# Orchestration UI

`MainWindow` reste le shell Qt et le point de raccordement des actions visibles.
Les responsabilités transverses sont progressivement déplacées vers des
adaptateurs dédiés :

- `WorkspaceController` capture et restaure l'état des tables, arbres,
  filtres, tris, onglet actif et splitter ;
- `SelectionManager` reste l'unique bus de sélection ;
- `DetailsProviderRegistry` sélectionne un provider de contenu sans coupler le
  `DetailsPanel` à une vue ou à un module métier.

Le `FileDetailsProvider` préserve strictement le rendu historique : fichier,
événement Timeline lié et bookmark résolu continuent à alimenter les mêmes
sections du panneau. De futurs providers (Investigation, Registry, YARA,
Hex Viewer) s'enregistrent après lui et peuvent donc prendre priorité pour
leur type de sélection, sans modifier le panneau partagé.
