"""
Hydra Cloud Shield — boxes/ghost.py
BOX2 — Ghost : surveillance passive et furtive.

Ghost poll aussi les Cloud Audit Logs (comme Scout), mais ne regarde pas
la sévérité ou le type de méthode — il construit un historique de
fréquence par identité et repère les patterns temporels anormaux :
horaires inhabituels, rafales d'activité, apparitions soudaines
d'identités jamais vues. Spécialisé dans ce qui essaie de se fondre
dans le bruit plutôt que ce qui hurle.
"""
import time
from collections import defaultdict
from datetime import datetime, timezone

from boxes.base_box import BaseBox
from core import audit_log_reader
from core.pubsub_ring import RingClient
from core.memory_store import MemoryStore
from config.settings import SCAN_INTERVAL_SECONDS

# Heures considérées "creuses" (UTC) — activité à ces heures = suspect
OFF_HOURS_START = 1
OFF_HOURS_END = 5

# Nombre d'événements dans une fenêtre de scan pour considérer une
# identité comme étant en "rafale" d'activité
BURST_THRESHOLD = 5


class Ghost(BaseBox):
    def __init__(self):
        super().__init__(box_name="ghost")
        self.ring = RingClient(self.box_name)
        self.memory = MemoryStore()
        self._seen_insert_ids = set()
        self._activity_count = defaultdict(int)  # identité -> nb d'événements ce cycle

    def _build_features(self, event: dict) -> dict:
        identity = event.get("principal_email", "unknown")
        timestamp_str = event.get("timestamp")

        is_off_hours = False
        if timestamp_str:
            try:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                is_off_hours = OFF_HOURS_START <= dt.hour < OFF_HOURS_END
            except ValueError:
                pass

        history = self.memory.get(identity)
        is_first_seen = history is None

        return {
            "identity": identity,
            "is_off_hours": is_off_hours,
            "is_first_seen": is_first_seen,
            "burst_count": self._activity_count[identity],
            "resource_name": event.get("resource_name", ""),
        }

    def _score(self, features: dict) -> tuple[float, list[str]]:
        score = 0.0
        raisons = []

        if features["is_off_hours"]:
            score += 25
            raisons.append("Activité en heures creuses (1h-5h UTC)")

        if features["is_first_seen"]:
            score += 20
            raisons.append("Identité jamais rencontrée auparavant")

        if features["burst_count"] >= BURST_THRESHOLD:
            score += 30
            raisons.append(f"Rafale d'activité détectée ({features['burst_count']} événements)")

        if not raisons:
            score = 3
            raisons.append("Aucun pattern temporel anormal détecté")

        return min(score, 100), raisons

    def run(self):
        print("[GHOST] 👻 Démarrage — surveillance passive des patterns temporels.")
        self.ring.start_heartbeat()  # signal de vie même sans alerte à publier
        while True:
            events = audit_log_reader.fetch_recent_events()
            new_events = [e for e in events if e.get("insert_id") not in self._seen_insert_ids]

            self._activity_count.clear()
            for event in new_events:
                self._activity_count[event.get("principal_email", "unknown")] += 1

            for event in new_events:
                self._seen_insert_ids.add(event.get("insert_id"))
                features = self._build_features(event)
                score, raisons = self._score(features)

                if score >= 20:
                    print(f"[GHOST] 👁️ Score {score}/100 — {features['identity']}")
                    for r in raisons:
                        print(f"         • {r}")

                    try:
                        self.ring.publish({
                            "proc_or_event_id": event.get("insert_id"),
                            "identity": features["identity"],
                            "score": score,
                            "confidence": 0.5,  # Ghost = signal faible mais utile en contexte
                            "features": features,
                            "raisons": raisons,
                        })
                    except Exception as e:
                        print(f"[GHOST] ⚠️ Publication ring échouée : {e}")

                    try:
                        self.memory.record_encounter(features["identity"], score, self.box_name)
                    except Exception as e:
                        print(f"[GHOST] ⚠️ Écriture mémoire échouée : {e}")

            if len(self._seen_insert_ids) > 5000:
                self._seen_insert_ids.clear()

            time.sleep(SCAN_INTERVAL_SECONDS)


def run():
    Ghost().run()


if __name__ == "__main__":
    # Test manuel : BOX_ROLE=ghost python -m boxes.ghost
    run()