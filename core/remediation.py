"""
Hydra Cloud Shield — core/remediation.py
Remplace sandbox_engine.mettre_en_quarantaine() (qui suspendait un PID
et copiait l'exécutable). Ici, la "quarantaine" d'une identité IAM
suspecte, c'est :
  - désactiver une clé de service account compromise
  - retirer un rôle IAM ajouté de façon suspecte

PHILOSOPHIE INCHANGÉE : REPAIR only, jamais d'action offensive.
L'humain valide TOUJOURS avant exécution — propose() ne fait QUE
construire une proposition (aucun appel IAM). execute_* ne doit être
appelé que depuis un point d'entrée déclenché par confirmation humaine
explicite (GUI, CLI avec confirmation, etc.) — jamais depuis Oracle
directement.
"""
import time

# from google.cloud import resourcemanager_v3, iam_admin_v1


def propose(verdict_context: dict) -> dict:
    """
    Construit une proposition de remédiation à partir du verdict Oracle.
    Ne modifie RIEN côté IAM. Retourne un dict décrivant l'action
    possible, destiné à être affiché à l'humain pour validation
    (console, GUI future, notification...).
    """
    identity = verdict_context.get("identity", "unknown")
    verdict = verdict_context.get("verdict", {})

    return {
        "identity": identity,
        "verdict": verdict.get("verdict"),
        "score": verdict.get("score"),
        "explanation": verdict.get("explanation"),
        "recommended_action": verdict.get("recommended_action", "none"),
        "proposed_at": time.time(),
        "status": "pending_human_confirmation",
    }


def execute_disable_service_account_key(key_name: str) -> bool:
    """Désactive une clé de service account. Appelé UNIQUEMENT après
    confirmation humaine explicite (jamais en automatique).

    TODO: implémenter via iam_admin_v1 — DisableServiceAccountKey.
    """
    raise NotImplementedError


def execute_revoke_iam_role(principal: str, role: str, resource: str) -> bool:
    """Retire un rôle IAM d'un principal sur une ressource donnée.
    Appelé UNIQUEMENT après confirmation humaine explicite.

    TODO: implémenter via resourcemanager_v3 — get + modify IAM policy.
    """
    raise NotImplementedError