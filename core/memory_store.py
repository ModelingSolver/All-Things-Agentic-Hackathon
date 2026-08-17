"""
Hydra Cloud Shield — core/memory_store.py
Remplace memory.py / memory.json (fichier local partagé par symlink).

Même interface conceptuelle que l'ancien memory.py (record_encounter,
get, is_known_safe, is_known_threat, avg_score...) mais backée par
Firestore au lieu d'un fichier JSON — ça règle nativement le problème
de concurrence entre boxes (plus besoin de threading.Lock() maison,
Firestore gère les écritures concurrentes).

Collection : hydra_memory (config.settings.MEMORY_COLLECTION)
Document ID : identité surveillée (proc_name, ou principal_email
pour la version cloud — probablement le meilleur candidat vu qu'on
surveille des identités IAM plutôt que des process).
"""
import time

from google.cloud import firestore

from config.settings import MEMORY_COLLECTION

MAX_SCORE_HISTORY = 20  # même limite que l'ancien memory.py local


class MemoryStore:
    def __init__(self):
        self.db = firestore.Client()
        self.collection = self.db.collection(MEMORY_COLLECTION)

    @staticmethod
    def _normalize_id(identity: str) -> str:
        """Firestore document IDs interdisent le '/' — on remplace au cas
        où une resource_name ou un principal_email en contiendrait."""
        return identity.lower().replace("/", "_")

    def record_encounter(self, identity: str, score: float, box_name: str, verdict: str = "unknown"):
        """Équivalent de l'ancien record_encounter — upsert atomique via
        une transaction Firestore pour éviter les races entre boxes qui
        écrivent sur la même identité en même temps."""
        doc_ref = self.collection.document(self._normalize_id(identity))

        @firestore.transactional
        def _update(transaction):
            snapshot = doc_ref.get(transaction=transaction)
            now = time.time()

            if snapshot.exists:
                data = snapshot.to_dict()
            else:
                data = {
                    "identity": identity,
                    "first_seen": now,
                    "last_seen": now,
                    "encounters": 0,
                    "verdict": "unknown",
                    "score_history": [],
                    "reported_by": [],
                }

            data["last_seen"] = now
            data["encounters"] = data.get("encounters", 0) + 1

            history = data.get("score_history", [])
            history.append(score)
            data["score_history"] = history[-MAX_SCORE_HISTORY:]

            reported_by = set(data.get("reported_by", []))
            reported_by.add(box_name)
            data["reported_by"] = list(reported_by)

            if verdict != "unknown":
                data["verdict"] = verdict

            transaction.set(doc_ref, data)

        transaction = self.db.transaction()
        _update(transaction)

    def get(self, identity: str) -> dict | None:
        doc = self.collection.document(self._normalize_id(identity)).get()
        return doc.to_dict() if doc.exists else None

    def set_verdict(self, identity: str, verdict: str):
        doc_ref = self.collection.document(self._normalize_id(identity))
        now = time.time()

        if doc_ref.get().exists:
            doc_ref.update({"verdict": verdict})
        else:
            doc_ref.set({
                "identity": identity,
                "first_seen": now,
                "last_seen": now,
                "encounters": 0,
                "verdict": verdict,
                "score_history": [],
                "reported_by": [],
            })

    def is_known_safe(self, identity: str) -> bool:
        entry = self.get(identity)
        return entry is not None and entry.get("verdict") == "safe"

    def is_known_threat(self, identity: str) -> bool:
        entry = self.get(identity)
        return entry is not None and entry.get("verdict") == "sandbox"

    def avg_score(self, identity: str) -> float:
        entry = self.get(identity)
        if not entry or not entry.get("score_history"):
            return 0.0
        history = entry["score_history"]
        return sum(history) / len(history)