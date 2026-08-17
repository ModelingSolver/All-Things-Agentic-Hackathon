"""
Hydra Cloud Shield — boxes/scout.py
BOX0 — Scout : première ligne de détection.

Rôle : poll les Cloud Audit Logs récents (via core.audit_log_reader),
détecte les événements à risque (changement IAM, clé de service account
créée, accès refusé répété...), calcule un score rapide avec des seuils
BAS (mieux vaut un faux positif qu'un événement raté), publie sur le ring.
"""
import time

from boxes.base_box import BaseBox
from core import audit_log_reader
from core.pubsub_ring import RingClient
from core.memory_store import MemoryStore
from config.settings import SCAN_INTERVAL_SECONDS

# Méthodes considérées à risque d'emblée — scoring immédiat élevé
HIGH_RISK_METHODS = [
    "SetIamPolicy",
    "google.iam.admin.v1.CreateServiceAccountKey",
    "google.iam.admin.v1.CreateServiceAccount",
]

# Sévérités qui méritent une attention même sans méthode à risque connue
WATCHED_SEVERITIES = ["WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]


class Scout(BaseBox):
    def __init__(self):
        super().__init__(box_name="scout")
        self._seen_insert_ids = set()  # évite de re-scorer le même événement 2 fois
        self.ring = RingClient(self.box_name)
        self.memory = MemoryStore()

    def _build_features(self, event: dict) -> dict:
        method = event.get("method_name", "")
        severity = event.get("severity", "DEFAULT")

        return {
            "method_name": method,
            "principal_email": event.get("principal_email", "unknown"),
            "resource_name": event.get("resource_name", ""),
            "is_high_risk_method": method in HIGH_RISK_METHODS,
            "is_watched_severity": severity in WATCHED_SEVERITIES,
            "severity": severity,
            "timestamp": event.get("timestamp"),
        }

    def _score(self, features: dict) -> tuple[float, list[str]]:
        score = 0.0
        raisons = []

        if features["is_high_risk_method"]:
            score += 50
            raisons.append(f"Méthode à risque : {features['method_name']}")

        if features["is_watched_severity"]:
            score += 25
            raisons.append(f"Sévérité surveillée : {features['severity']}")

        if features["principal_email"] == "unknown":
            score += 15
            raisons.append("Identité de l'auteur non résolue")

        if not raisons:
            # Rien de spécifique détecté, mais on garde une trace basse
            # plutôt que de ne rien publier — le Tank/Oracle peuvent
            # vouloir voir même les événements "calmes" pour du contexte.
            score = 5
            raisons.append("Événement de routine, pas de signal fort")

        return min(score, 100), raisons

    def run(self):
        print("[SCOUT] 🔍 Démarrage — surveillance des Cloud Audit Logs.")
        while True:
            events = audit_log_reader.fetch_recent_events()
            new_events = [e for e in events if e.get("insert_id") not in self._seen_insert_ids]

            for event in new_events:
                self._seen_insert_ids.add(event.get("insert_id"))
                features = self._build_features(event)
                score, raisons = self._score(features)

                if score >= 20:  # seuil bas volontaire — Scout est le premier filtre
                    print(f"[SCOUT] ⚠️ Score {score}/100 — {features['method_name']} "
                          f"par {features['principal_email']}")
                    for r in raisons:
                        print(f"         • {r}")

                    identity = features["principal_email"]

                    try:
                        self.ring.publish({
                            "proc_or_event_id": event.get("insert_id"),
                            "identity": identity,
                            "score": score,
                            "confidence": 0.6,  # Scout = première passe, confiance modérée
                            "features": features,
                            "raisons": raisons,
                        })
                    except Exception as e:
                        print(f"[SCOUT] ⚠️ Publication ring échouée : {e}")

                    try:
                        self.memory.record_encounter(identity, score, self.box_name)
                    except Exception as e:
                        print(f"[SCOUT] ⚠️ Écriture mémoire échouée : {e}")

            # Purge simple pour éviter que _seen_insert_ids grossisse indéfiniment
            if len(self._seen_insert_ids) > 5000:
                self._seen_insert_ids.clear()

            time.sleep(SCAN_INTERVAL_SECONDS)


def run():
    Scout().run()


if __name__ == "__main__":
    # Test manuel : BOX_ROLE=scout python -m boxes.scout
    run()