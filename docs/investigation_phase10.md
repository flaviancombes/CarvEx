# Module Investigation — Phase 10 : Journal

Le Journal est un consommateur passif et append-only des événements publiés par
`InvestigationService`. Le Service ne crée jamais directement une entrée : le
`JournalSubscriber` convertit chaque `InvestigationEvent` reçu en une
`InvestigationJournalEntry` minimale.

Une entrée stocke seulement son identifiant, l'horodatage de l'événement, son
type, une cible et un parent optionnels, un contexte textuel minimal et l'auteur
lorsqu'il est connu. Elle ne copie jamais un objet Investigation ou DFIR.

Le store primaire est `journal`. Les index reconstruisibles sont :

- `entry_id → InvestigationJournalEntry`
- `timestamp → entry_ids`
- `event_type → entry_ids`
- `target_ref → entry_ids`

Le subscriber est abonné automatiquement lors de l'initialisation du module et
désabonné à sa fermeture. Les APIs de consultation sont `list_entries`,
`find_entries_for_target`, `find_entries_by_event_type` et
`find_entries_between_dates`. Il n'existe volontairement aucune API de création,
modification ou suppression du Journal.

Le schéma Investigation passe à la version 4. La migration `3 → 4` déclare le
store logique `journal`, sans créer de donnée primaire.

La Recherche, les Rapports, la vue Investigation et les modèles Qt restent hors
périmètre.
