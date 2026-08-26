# Module Investigation — Phase 8 : Hypothèses

`InvestigationHypothesis` représente un raisonnement de l'analyste. Elle ne
possède aucune preuve ni objet DFIR : ses éléments sont des
`HypothesisMembership` référençant exclusivement une `InvestigationTargetRef`.

Le statut décrit l'avancement du raisonnement (`DRAFT`, `IN_PROGRESS`,
`CONCLUDED`, `ARCHIVED`). La confiance est distincte (`UNKNOWN`, `LOW`,
`MEDIUM`, `HIGH`, `CONFIRMED`, `REJECTED`) : une hypothèse peut donc rester en
cours tout en ayant une confiance forte, ou être conclue avec une confiance
rejetée.

Le rôle d'un élément est typé par `HypothesisRole` : `SUPPORTS`,
`CONTRADICTS`, `OBSERVATION`, `SOURCE`, `RESULT` ou `REFERENCE`.

Les stores primaires sont `hypotheses` et `hypothesis_memberships`. Les index
reconstruisibles sont :

- `hypothesis_id → InvestigationHypothesis`
- `target_ref → hypothesis_ids`
- `hypothesis_id → target_refs`
- `role → membership_ids`

L'unicité du couple `(hypothesis_id, target_ref)` est garantie. Supprimer une
hypothèse supprime uniquement ses memberships, jamais les cibles référencées.

Le schéma Investigation passe à la version 3. La migration `2 → 3` déclare
les stores logiques des Hypothèses sans écrire de donnée primaire.

API publique : `create_hypothesis`, `update_hypothesis`, `delete_hypothesis`,
`get_hypothesis`, `list_hypotheses`, `add_to_hypothesis`,
`remove_from_hypothesis`, `find_hypothesis_members` et
`find_hypotheses_for_target`.

Le Journal, les événements métier, la Recherche, la vue Investigation et les
modèles Qt restent hors périmètre.
