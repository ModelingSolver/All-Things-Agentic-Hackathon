"""
Hydra Cloud Shield — boxes/base_box.py
Classe abstraite partagée par toutes les boxes.
Reprend le cycle du système local (scan → score → publish → écoute)
mais sur les briques cloud (Pub/Sub, Firestore) au lieu de UDP/fichier.

Chaque box concrète (scout.py, tank.py...) hérite de BaseBox et
implémente sa propre logique de scoring (_build_features, _score).
"""
from abc import ABC, abstractmethod


class BaseBox(ABC):
    def __init__(self, box_name: str):
        self.box_name = box_name
        # Les clients partagés (ring, memory) sont instanciés dans
        # chaque box concrète, selon ses besoins réels.

    @abstractmethod
    def _build_features(self, event: dict) -> dict:
        """Construit le vecteur de features à partir d'un événement
        (log Cloud Audit, ou paquet ring reçu d'une autre box)."""
        raise NotImplementedError

    @abstractmethod
    def _score(self, features: dict) -> tuple[float, list[str]]:
        """Retourne (score 0-100, raisons) à partir des features."""
        raise NotImplementedError

    def run(self):
        """Boucle principale — implémentée par chaque box concrète."""
        raise NotImplementedError
