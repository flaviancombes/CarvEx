# Module Investigation — Phase 4 : Notes

Cette phase ajoute `InvestigationNote`, une entité autonome de documentation. Une note cible zéro ou une `InvestigationTargetRef` et ne modifie jamais sa cible.

Les formats typés sont `PLAIN_TEXT` et `MARKDOWN`. Seul le texte brut est utilisé ; aucun rendu Markdown n'est fourni.

Les notes sont persistées individuellement dans le store primaire `notes`. Les index reconstruisibles sont :

- `note_id → InvestigationNote`
- `target_ref → note_ids`
- `author → note_ids`

API publique : `create_note`, `update_note`, `delete_note`, `get_note`, `list_notes` et `find_notes_for_target`.

Pièces jointes, références croisées, collections, tags, hypothèses, affaires, journal, recherche et vues Qt restent hors périmètre.
