"""
Hydra Cloud Shield — main.py
Point d'entrée unique du service Cloud Run.

Le rôle joué (Scout / Tank / Ghost / Oracle / Druid) est déterminé par la
variable d'environnement BOX_ROLE. Ça permet de déployer le MÊME conteneur
5 fois avec un paramètre différent, plutôt que 5 images séparées à maintenir.

Usage local :
    BOX_ROLE=scout python main.py

Déploiement Cloud Run (voir deploy.sh) :
    gcloud run deploy hydra-scout --set-env-vars BOX_ROLE=scout ...
    gcloud run deploy hydra-tank  --set-env-vars BOX_ROLE=tank ...
    etc.
"""
import importlib
import os
import sys

BOX_REGISTRY = {
    "scout": "boxes.scout",
    "tank": "boxes.tank",
    "ghost": "boxes.ghost",
    "oracle": "boxes.oracle",
    "druid": "boxes.druid",
}

REQUIRED_ENV_VARS = ["GCP_PROJECT_ID", "HYDRA_RING_HMAC_KEY"]


def _check_env():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print(f"[HYDRA] ❌ Variables d'environnement manquantes : {', '.join(missing)}")
        print("[HYDRA] Voir .env.example pour la liste complète.")
        sys.exit(1)


def main():
    role = os.environ.get("BOX_ROLE", "").lower()

    if role not in BOX_REGISTRY:
        print(f"[HYDRA] ❌ BOX_ROLE invalide ou absent : '{role}'")
        print(f"[HYDRA] Rôles valides : {', '.join(BOX_REGISTRY.keys())}")
        sys.exit(1)

    _check_env()

    print(f"[HYDRA] 🚀 Démarrage en rôle : {role.upper()}")

    module = importlib.import_module(BOX_REGISTRY[role])

    try:
        module.run()
    except KeyboardInterrupt:
        print(f"\n[HYDRA] 🛑 Arrêt manuel de {role.upper()}.")
    except Exception as e:
        # Ne jamais laisser Cloud Run redémarrer en boucle silencieusement
        # sur une erreur de config — on log clairement avant de sortir.
        print(f"[HYDRA] ❌ {role.upper()} a crashé : {e}")
        raise


if __name__ == "__main__":
    main()