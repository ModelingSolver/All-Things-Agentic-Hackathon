"""
Hydra Cloud Shield — core/pubsub_ring.py
Remplace le ring UDP + signature HMAC de la version locale.

Chaque box publie ses RingPacket (score, features, box source) sur un
topic Pub/Sub unique ('hydra-ring'), et s'abonne à sa propre subscription
pour recevoir les paquets des autres boxes. La signature HMAC est
conservée (même logique que l'ancien box_logic.py patché) pour garder
la protection contre l'injection de faux scores.

Structure du RingPacket (reprise du README Hydra-Smart-Shield) :
    {
        "source_role": str,
        "proc_or_event_id": str,
        "score": float,
        "confidence": float,
        "features": dict,
        "timestamp": float,
        "signature": str,  # HMAC-SHA256
    }
"""
import hashlib
import hmac
import json
import os
import time

from google.cloud import pubsub_v1
from google.api_core.exceptions import AlreadyExists, NotFound

from config.settings import PROJECT_ID, RING_TOPIC, RING_SUBSCRIPTION_PREFIX

# Clé partagée pour signer les paquets — en prod, passe par Secret Manager.
# En local/dev, une variable d'env fait l'affaire pour le hackathon.
_HMAC_KEY = os.environ.get("HYDRA_RING_HMAC_KEY", "").encode()


def _sign(payload_bytes: bytes) -> str:
    if not _HMAC_KEY:
        raise RuntimeError(
            "HYDRA_RING_HMAC_KEY non configurée — impossible de signer les paquets."
        )
    return hmac.new(_HMAC_KEY, payload_bytes, hashlib.sha256).hexdigest()


def _verify(payload_bytes: bytes, signature: str) -> bool:
    if not _HMAC_KEY:
        return False
    expected = _sign(payload_bytes)
    # comparaison à temps constant — évite les timing attacks sur la vérif
    return hmac.compare_digest(expected, signature)


class RingClient:
    def __init__(self, box_name: str):
        self.box_name = box_name
        self.publisher = pubsub_v1.PublisherClient()
        self.subscriber = pubsub_v1.SubscriberClient()
        self.topic_path = self.publisher.topic_path(PROJECT_ID, RING_TOPIC)
        self.subscription_path = self.subscriber.subscription_path(
            PROJECT_ID, f"{RING_SUBSCRIPTION_PREFIX}{box_name}"
        )
        self._ensure_topic()
        self._ensure_subscription()

    def _ensure_topic(self):
        try:
            self.publisher.create_topic(request={"name": self.topic_path})
            print(f"[RING] Topic créé : {RING_TOPIC}")
        except AlreadyExists:
            pass  # déjà là, tant mieux

    def _ensure_subscription(self):
        try:
            self.subscriber.create_subscription(
                request={"name": self.subscription_path, "topic": self.topic_path}
            )
            print(f"[RING][{self.box_name}] Subscription créée.")
        except AlreadyExists:
            pass

    def publish(self, payload: dict):
        """Signe et publie un paquet sur le topic partagé.
        Toutes les boxes (y compris l'émettrice) le recevront —
        c'est à listen() de filtrer les paquets qu'on a soi-même émis."""
        enriched = {
            **payload,
            "source_role": self.box_name,
            "timestamp": payload.get("timestamp", time.time()),
        }
        body = json.dumps(enriched, sort_keys=True).encode("utf-8")
        signature = _sign(body)

        future = self.publisher.publish(
            self.topic_path,
            data=body,
            signature=signature,
            source_role=self.box_name,
        )
        future.result(timeout=10)  # attend la confirmation de publication

    def listen(self, callback, block: bool = True):
        """S'abonne au topic et appelle callback(payload: dict) pour chaque
        paquet valide reçu (signature vérifiée, pas émis par soi-même).
        Rejette silencieusement les paquets invalides — log un warning
        mais ne fait jamais planter la box (pourrait être une attaque
        d'injection ring, pas juste un bug)."""

        def _on_message(message):
            try:
                signature = message.attributes.get("signature", "")
                source_role = message.attributes.get("source_role", "")

                if source_role == self.box_name:
                    message.ack()  # on ignore ses propres paquets, mais on ack pour pas les revoir
                    return

                if not _verify(message.data, signature):
                    print(f"[RING][{self.box_name}] ⚠️ Paquet rejeté — signature invalide "
                          f"(source prétendue: {source_role})")
                    message.ack()  # on ack quand même pour ne pas le retraiter en boucle
                    return

                payload = json.loads(message.data.decode("utf-8"))
                callback(payload)
                message.ack()
            except Exception as e:
                print(f"[RING][{self.box_name}] ⚠️ Erreur traitement message : {e}")
                message.nack()  # on retente plus tard, ce n'était peut-être qu'un souci ponctuel

        streaming_pull_future = self.subscriber.subscribe(self.subscription_path, callback=_on_message)
        print(f"[RING][{self.box_name}] 👂 En écoute sur {self.subscription_path}")

        if block:
            try:
                streaming_pull_future.result()
            except KeyboardInterrupt:
                streaming_pull_future.cancel()
        else:
            # laisse tourner en arrière-plan, l'appelant garde la main
            return streaming_pull_future