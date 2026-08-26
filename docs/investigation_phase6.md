# Module Investigation — Phase 6 : Cases

`InvestigationCase` est l'agrégat logique racine du module Investigation. Elle organise des références légères sans copier les éléments qu'elle regroupe.

Les statuses sont `OPEN`, `IN_PROGRESS`, `ON_HOLD`, `CLOSED` et `ARCHIVED`. Les priorités sont typées par `CasePriority`.

Les memberships `CaseMembership` sont persistés indépendamment dans `case_memberships`, avec les Cases dans `cases`. Ils utilisent uniquement `InvestigationTargetRef` et garantissent l'unicité du couple `(case_id, target_ref)`.

Les index reconstruisibles sont :

- `case_id → InvestigationCase`
- `target_ref → case_ids`
- `case_id → target_refs`

API publique : `create_case`, `update_case`, `delete_case`, `get_case`, `list_cases`, `add_to_case`, `remove_from_case`, `find_case_members` et `find_cases_for_target`.

La suppression d'une Case supprime ses memberships, jamais les objets qu'ils référencent. Collections, hypothèses, journal, recherche et vues Qt restent hors périmètre.
