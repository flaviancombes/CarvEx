# EventBus Investigation

`EventBus` diffuse les `DomainEvent` de manière strictement synchrone, dans
l'ordre d'abonnement. Il ne met aucun événement en file et n'exécute aucune
tâche en arrière-plan.

## Abonnement et désabonnement

Les abonnements sont dédupliqués par callable et filtre d'événement. Pour
une méthode liée, l'identité est le couple `instance + fonction`, plutôt que
l'objet méthode temporaire créé par Python. Ainsi,
`bus.unsubscribe(instance.method)` fonctionne même si la méthode est relue
au moment du désabonnement.

`unsubscribe()` retire toutes les inscriptions de ce subscriber, quel que soit
leur filtre, et doit être appelé pendant la fermeture du consommateur.

## Politique d'erreur

Une exception levée par un subscriber est capturée, journalisée avec la
trace complète, puis isolée. La publication continue vers les subscribers
suivants et l'exception n'est pas renvoyée au service Investigation.

Cette politique est volontaire : une intégration UI ou optionnelle ne doit
jamais annuler une commande déjà appliquée, ni empêcher le Journal, abonné
lors de l'initialisation du module, de recevoir l'événement. Une panne du
Journal lui-même reste consignée dans les logs et doit être traitée comme
une anomalie d'exploitation ; l'EventBus ne tente ni rollback ni correction
automatique.
