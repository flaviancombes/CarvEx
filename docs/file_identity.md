# Identité canonique des preuves fichier

Chaque fichier importé reçoit un `file_id` UUID v5 déterministe selon le
schéma `content-provenance-v1`. Son matériau d'identité est strictement :

- le SHA-256 obligatoire du contenu ;
- le `source_path` obligatoire normalisé lexicalement (Unicode NFC et
  séparateurs `/`).

L'ordre, la position du rapport, le nom affiché, le chemin d'export, la taille,
le MIME, les caches et le namespace de projet n'interviennent jamais dans
l'identité.

Cette combinaison préserve deux propriétés DFIR :

- un rapport réordonné ou enrichi redonne les mêmes `file_id` ;
- un contenu ou une provenance modifiés donnent un nouveau `file_id`.

Dans le second cas, les références existantes restent attachées à leur preuve
historique et deviennent non résolues dans le nouveau corpus. Elles ne peuvent
donc jamais être redirigées silencieusement vers un autre fichier.

Deux entrées ayant simultanément le même SHA-256 et le même `source_path` sont
ambiguës sans utiliser l'index de rapport. CarvEx refuse explicitement un tel
rapport au lieu d'inventer une identité.

## Compatibilité historique

Les projets antérieurs utilisaient `file_identity_namespace` et la position de
l'entrée dans le rapport. Ce schéma ne contient aucun registre permettant de
retrouver avec certitude les cibles persistées après un remplacement,
un réordonnancement ou une modification du rapport.

Un projet dont `file_identity_scheme` est absent mais qui porte un namespace
historique est donc ouvert sans corpus source ; le chargement du rapport est
refusé explicitement. Il faut créer un nouveau projet et réassocier les
preuves de manière contrôlée. Cette décision évite une migration destructive.

Tous les consommateurs — caches de métadonnées et d'artefacts, Timeline,
Bookmarks, DuplicateIndex, sélection et `InvestigationTargetRef(kind="file")`
— utilisent exclusivement `file_id`.
