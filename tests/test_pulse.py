"""
Hydra Cloud Shield — tests/test_pulse.py
Adapté de l'ancien test_pulse.py (qui envoyait un paquet UDP direct
au Scout). Ici, on publie un événement de test sur le topic Pub/Sub
'hydra-ring' pour vérifier que la chaîne complète réagit, SANS
dépendre de vrais Cloud Audit Logs — utile pour débugger le pipeline
indépendamment de la source réelle.

Ne remplace PAS le fonctionnement autonome normal (qui lit les vrais
logs via core.audit_log_reader) — c'est un outil de test seulement.
"""
# from core.pubsub_ring import RingClient

TEST_EVENT = {
    "source_role": "test_injector",
    "proc_or_event_id": "test-suspicious-iam-change",
    "score": 85.0,
    "confidence": 0.9,
    "features": {
        "method_name": "SetIamPolicy",
        "principal_email": "test-fake-account@example.com",
        "resource_name": "projects/test-project",
    },
}


def pulse():
    # TODO: RingClient("test").publish(TEST_EVENT)
    print("[TEST] Pulse envoyé sur hydra-ring. Vérifie les logs des boxes.")
    raise NotImplementedError


if __name__ == "__main__":
    pulse()