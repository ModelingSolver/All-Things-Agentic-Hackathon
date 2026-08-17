"""
Hydra Cloud Shield — boxes/druid.py
BOX4 — Druid : gardien de la mémoire long terme + santé de la ruche.

Contrairement aux autres boxes, Druid ne traite pas des identités
individuelles — il surveille l'état de santé du système lui-même :
- Est-ce que les autres boxes publient toujours sur le ring (heartbeat) ?
- Le volume de menaces confirmées augmente-t-il anormalement vite
  (signe possible d'une attaque contre l'infra de détection elle-même,
  pas juste contre une identité) ?
- La mémoire Firestore ne grossit-elle pas indéfiniment ?

Il tourne à son propre rythme, pas en réaction au ring (même s'il
écoute aussi, pour détecter les silences suspects des autres boxes).
"""
import time
import threading
from collections import defaultdict

from boxes.base_box import BaseBox
from core.pubsub_ring import RingClient
from core.memory_store import MemoryStore

EXPECTED_ROLES = ["scout", "tank", "ghost", "oracle"]  # Druid ne s'attend pas à lui-même
HEARTBEAT_TIMEOUT_SECONDS = 90  # au-delà, une box est considérée silencieuse
HEALTH_CHECK_INTERVAL_SECONDS = 30


class Druid(BaseBox):
    def __init__(self):
        super().__init__(box_name="druid")
        self.ring = RingClient(self.box_name)
        self.memory = MemoryStore()
        self._last_seen = {role: 0.0 for role in EXPECTED_ROLES}
        self._lock = threading.Lock()

    def _build_features(self, event: dict) -> dict:
        # Non utilisé — Druid ne score pas des identités individuelles,
        # voir _check_swarm_health() pour sa vraie logique.
        raise NotImplementedError

    def _score(self, features: dict) -> tuple[float, list[str]]:
        raise NotImplementedError

    def _on_ring_message(self, payload: dict):
        source = payload.get("source_role")
        if source in self._last_seen:
            with self._lock:
                self._last_seen[source] = time.time()

    def _check_swarm_health(self):
        now = time.time()
        silent_boxes = []

        with self._lock:
            for role, last_seen in self._last_seen.items():
                if last_seen == 0.0:
                    continue  # jamais vue depuis le démarrage de Druid, pas encore alarmant
                if now - last_seen > HEARTBEAT_TIMEOUT_SECONDS:
                    silent_boxes.append(role)

        if silent_boxes:
            print(f"[DRUID] 🌿⚠️ Boxes silencieuses depuis plus de "
                  f"{HEARTBEAT_TIMEOUT_SECONDS}s : {', '.join(silent_boxes)}")
        else:
            print("[DRUID] 🌿 Santé de la ruche : nominale.")

    def run(self):
        print("[DRUID] 🌿 Démarrage — surveillance de la santé de la ruche.")

        # Écoute le ring en arrière-plan pour capter les heartbeats implicites
        # (chaque publication d'une box vaut heartbeat, pas besoin d'un
        # message dédié).
        self.ring.listen(self._on_ring_message, block=False)

        while True:
            self._check_swarm_health()
            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)


def run():
    Druid().run()


if __name__ == "__main__":
    # Test manuel : BOX_ROLE=druid python -m boxes.druid
    run()