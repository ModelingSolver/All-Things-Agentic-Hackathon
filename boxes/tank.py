"""
Hydra Cloud Shield — boxes/tank.py
BOX1 — Tank : analyse lourde et méthodique.

Contrairement à Scout, Tank ne poll pas les Cloud Audit Logs directement —
il écoute le ring Pub/Sub pour les alertes que Scout a déjà remontées,
et creuse l'historique Firestore de l'identité concernée avant de
confirmer ou infirmer. Seuils plus élevés, moins de faux positifs :
Tank a le luxe de prendre son temps puisque Scout a déjà fait le tri rapide.
"""
from boxes.base_box import BaseBox
from core.pubsub_ring import RingClient
from core.memory_store import MemoryStore

# Nombre minimum de rencontres passées pour qu'un historique soit
# considéré significatif (sinon trop peu de données pour trancher)
MIN_ENCOUNTERS_FOR_HISTORY = 3


class Tank(BaseBox):
    def __init__(self):
        super().__init__(box_name="tank")
        self.ring = RingClient(self.box_name)
        self.memory = MemoryStore()

    def _build_features(self, event: dict) -> dict:
        """Ici, 'event' est en réalité le RingPacket publié par Scout
        (ou une autre box), pas un log brut."""
        identity = event.get("identity", "unknown")
        history = self.memory.get(identity)

        return {
            "identity": identity,
            "scout_score": event.get("score", 0),
            "scout_raisons": event.get("raisons", []),
            "history_exists": history is not None,
            "encounters": history.get("encounters", 0) if history else 0,
            "avg_past_score": self.memory.avg_score(identity),
            "known_verdict": history.get("verdict", "unknown") if history else "unknown",
        }

    def _score(self, features: dict) -> tuple[float, list[str]]:
        raisons = []

        # Verdict déjà connu -> décision immédiate, pas de recalcul
        if features["known_verdict"] == "safe":
            return 0, ["Identité déjà connue comme sûre — verdict mémorisé"]
        if features["known_verdict"] == "sandbox":
            return 95, ["Identité déjà connue comme menace confirmée — verdict mémorisé"]

        score = features["scout_score"] * 0.6  # on pondère l'alerte initiale de Scout
        raisons.append(f"Score Scout initial pondéré : {score:.0f}")

        if features["encounters"] >= MIN_ENCOUNTERS_FOR_HISTORY:
            avg = features["avg_past_score"]
            if avg > 50:
                score += 20
                raisons.append(f"Historique défavorable — score moyen passé : {avg:.0f}")
            elif avg < 15:
                score -= 15
                raisons.append(f"Historique favorable — score moyen passé : {avg:.0f}")
        else:
            # Pas assez d'historique pour trancher fort dans un sens ou l'autre
            raisons.append("Historique insuffisant pour ajuster la confiance")

        return max(0, min(score, 100)), raisons

    def _on_ring_message(self, payload: dict):
        # Tank ne traite que les alertes venant du Scout — évite de
        # se répondre à lui-même ou de traiter les signaux d'autres boxes
        # qui n'ont pas vocation à être re-confirmés par Tank.
        if payload.get("source_role") != "scout":
            return

        features = self._build_features(payload)
        score, raisons = self._score(features)

        print(f"[TANK] 🔬 Analyse de {features['identity']} — score confirmé : {score:.0f}/100")
        for r in raisons:
            print(f"        • {r}")

        try:
            self.ring.publish({
                "proc_or_event_id": payload.get("proc_or_event_id"),
                "identity": features["identity"],
                "score": score,
                "confidence": 0.8,  # Tank a plus de contexte que Scout
                "features": features,
                "raisons": raisons,
            })
        except Exception as e:
            print(f"[TANK] ⚠️ Publication ring échouée : {e}")

        try:
            self.memory.record_encounter(features["identity"], score, self.box_name)
        except Exception as e:
            print(f"[TANK] ⚠️ Écriture mémoire échouée : {e}")

    def run(self):
        print("[TANK] 🛡️ Démarrage — en attente des alertes Scout sur le ring.")
        self.ring.listen(self._on_ring_message)  # bloquant, tourne indéfiniment


def run():
    Tank().run()


if __name__ == "__main__":
    # Test manuel : BOX_ROLE=tank python -m boxes.tank
    run()