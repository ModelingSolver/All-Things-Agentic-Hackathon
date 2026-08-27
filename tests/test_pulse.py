"""
Hydra Cloud Shield — tests/test_pulse.py
Injecte un signal SYNTHÉTIQUE de menace critique dans le pipeline réel
(Pub/Sub signé HMAC → Tank confirme → Oracle appelle Gemini → verdict →
Firestore → dashboard live) — utile pour une démo reproductible, sans
attendre qu'un vrai événement IAM critique survienne naturellement.

RIEN n'est simulé côté infrastructure : le paquet passe par le vrai
ring signé, Oracle fait un vrai appel à Gemini, le verdict est vraiment
écrit dans Firestore et apparaît en temps réel sur le dashboard. Seul
le déclencheur (cet événement) est fabriqué — l'identité utilisée est
explicitement un compte de démo, pas une vraie identité.

Prérequis : Scout, Tank, Oracle, Druid doivent déjà tourner (voir
README section "Lancer le système en local") — ce script n'en est
pas un remplacement, juste un déclencheur supplémentaire.

Usage :
    python -m tests.test_pulse
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pubsub_ring import RingClient

DEMO_IDENTITY = "demo-critical-scenario@hydra-cloud-shield.iam.gserviceaccount.com"

CRITICAL_EVENT = {
    "proc_or_event_id": f"demo-pulse-{int(time.time())}",
    "identity": DEMO_IDENTITY,
    "score": 88.0,
    "confidence": 0.9,
    "features": {
        "method_name": "SetIamPolicy",
        "principal_email": DEMO_IDENTITY,
        "resource_name": "projects/hydra-cloud-shield",
        "is_high_risk_method": True,
        "is_watched_severity": True,
        "severity": "CRITICAL",
        "timestamp": time.time(),
    },
    "raisons": [
        "[DEMO] Élévation de privilège détectée : ajout du rôle roles/owner",
        "[DEMO] Aucun historique préalable pour cette identité",
        "[DEMO] Action effectuée en dehors des heures ouvrées habituelles",
    ],
}


def pulse():
    print("[TEST_PULSE] 🧪 Injection d'un scénario critique SYNTHÉTIQUE dans hydra-ring...")
    print(f"[TEST_PULSE]    Identité de démo : {DEMO_IDENTITY}")
    print("[TEST_PULSE]    (ceci n'est PAS un vrai événement IAM — signal de test contrôlé)")

    # On publie en se faisant passer pour Scout — c'est le point d'entrée
    # naturel du pipeline, Tank est configuré pour n'écouter QUE Scout.
    ring = RingClient("scout")
    ring.publish(CRITICAL_EVENT)

    print("[TEST_PULSE] ✅ Pulse envoyé sur hydra-ring.")
    print("[TEST_PULSE]    Surveille les logs de Tank et Oracle, et le dashboard :")
    print("[TEST_PULSE]    https://hydra-cloud-shield.web.app")
    print("[TEST_PULSE]    Oracle va accumuler les signaux ~15s avant d'appeler Gemini.")


if __name__ == "__main__":
    pulse()