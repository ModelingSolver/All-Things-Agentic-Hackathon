"""
Hydra Cloud Shield — boxes/oracle.py
BOX3 — Oracle : agrégateur + consensus final.

C'EST ICI que Gemini rentre dans la boucle (requirement obligatoire
du hackathon). L'Oracle reçoit les scores/features de Scout, Tank et
Ghost via le ring, accumule les signaux par identité pendant une courte
fenêtre, puis construit un prompt structuré avec le contexte complet
(signaux + historique Firestore) et appelle Gemini via
core.gemini_client pour trancher/expliquer le verdict.

Si le verdict dépasse le seuil critique, déclenche une PROPOSITION
de remédiation (jamais une action directe — confirmation humaine
requise, voir core.remediation).
"""
import time
import threading
from collections import defaultdict

from boxes.base_box import BaseBox
from core.pubsub_ring import RingClient
from core.memory_store import MemoryStore
from core import gemini_client
from core import remediation
from config.settings import ALERT_THRESHOLD_HIGH

# Fenêtre pendant laquelle on accumule les signaux d'une même identité
# avant de trancher — laisse le temps à Tank/Ghost de réagir à Scout.
CONSENSUS_WINDOW_SECONDS = 15


class Oracle(BaseBox):
    def __init__(self):
        super().__init__(box_name="oracle")
        self.ring = RingClient(self.box_name)
        self.memory = MemoryStore()
        self._pending_signals = defaultdict(list)  # identity -> [RingPacket, ...]
        self._pending_timers = {}
        self._lock = threading.Lock()

    def _build_features(self, event: dict) -> dict:
        # Non utilisé directement ici — Oracle travaille sur des groupes
        # de signaux plutôt que sur un événement isolé (voir _finalize_consensus).
        raise NotImplementedError

    def _score(self, features: dict) -> tuple[float, list[str]]:
        raise NotImplementedError

    def _on_ring_message(self, payload: dict):
        identity = payload.get("identity")
        if not identity:
            return

        with self._lock:
            self._pending_signals[identity].append(payload)

            # (Re)programme le trancheur de consensus pour cette identité —
            # si un nouveau signal arrive avant l'échéance, on repousse
            # légèrement pour laisser une chance aux autres boxes de répondre.
            if identity in self._pending_timers:
                self._pending_timers[identity].cancel()

            timer = threading.Timer(
                CONSENSUS_WINDOW_SECONDS,
                self._finalize_consensus,
                args=[identity],
            )
            timer.daemon = True
            timer.start()
            self._pending_timers[identity] = timer

    def _finalize_consensus(self, identity: str):
        with self._lock:
            signals = self._pending_signals.pop(identity, [])
            self._pending_timers.pop(identity, None)

        if not signals:
            return

        history = self.memory.get(identity)
        event = {"identity": identity}

        print(f"[ORACLE] 🔮 Consensus pour {identity} — {len(signals)} signal(aux) reçu(s)")

        verdict = gemini_client.get_consensus_verdict(event, signals, history)

        print(f"[ORACLE] ⚖️ Verdict Gemini : {verdict['verdict'].upper()} "
              f"(score {verdict['score']}/100, accord: {verdict.get('agents_agreement', '?')})")
        print(f"          {verdict['explanation']}")

        try:
            self.memory.record_encounter(
                identity, verdict["score"], self.box_name, verdict=verdict["verdict"]
            )
        except Exception as e:
            print(f"[ORACLE] ⚠️ Écriture mémoire échouée : {e}")

        if verdict["score"] >= ALERT_THRESHOLD_HIGH and verdict["verdict"] != "safe":
            self._propose_remediation(identity, verdict)

    def _propose_remediation(self, identity: str, verdict: dict):
        proposal = remediation.propose({"identity": identity, "verdict": verdict})
        print(f"[ORACLE] 🚨 Proposition de remédiation générée pour {identity} "
              f"— action recommandée : {verdict.get('recommended_action')}")
        print("          ⏸️  En attente de confirmation humaine avant exécution.")
        return proposal

    def run(self):
        print("[ORACLE] 🔮 Démarrage — écoute du ring, consensus piloté par Gemini.")
        self.ring.start_heartbeat()  # signal de vie même sans consensus à publier
        self.ring.listen(self._on_ring_message)  # bloquant


def run():
    Oracle().run()


if __name__ == "__main__":
    # Test manuel : BOX_ROLE=oracle python -m boxes.oracle
    run()