"""
Hydra Cloud Shield — core/remediation.py
Remplace sandbox_engine.mettre_en_quarantaine() (qui suspendait un PID
et copiait l'exécutable). Ici, la "quarantaine" d'une identité IAM
suspecte, c'est :
  - désactiver une clé de service account compromise
  - retirer un rôle IAM ajouté de façon suspecte

PHILOSOPHIE INCHANGÉE : REPAIR only, jamais d'action offensive.
L'humain valide TOUJOURS avant exécution — propose() ne fait QUE
construire et persister une proposition (aucun appel IAM). execute_*
ne doit être appelé que depuis tools/remediate.py, après confirmation
humaine explicite en console — jamais depuis Oracle directement.
"""
import time
import uuid

from google.cloud import firestore
from google.cloud import resourcemanager_v3
from google.cloud import iam_admin_v1

PROPOSALS_COLLECTION = "hydra_remediation_proposals"

_db = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client()
    return _db


def propose(verdict_context: dict) -> dict:
    """
    Construit une proposition de remédiation à partir du verdict Oracle
    et la persiste dans Firestore avec le statut 'pending'. Ne modifie
    RIEN côté IAM. Le CLI (tools/remediate.py) lira cette collection
    pour présenter les propositions à l'humain.
    """
    identity = verdict_context.get("identity", "unknown")
    verdict = verdict_context.get("verdict", {})

    proposal_id = str(uuid.uuid4())[:8]
    proposal = {
        "proposal_id": proposal_id,
        "identity": identity,
        "verdict": verdict.get("verdict"),
        "score": verdict.get("score"),
        "explanation": verdict.get("explanation"),
        "recommended_action": verdict.get("recommended_action", "none"),
        "proposed_at": time.time(),
        "status": "pending_human_confirmation",
    }

    try:
        db = _get_db()
        db.collection(PROPOSALS_COLLECTION).document(proposal_id).set(proposal)
    except Exception as e:
        # Même si la persistance échoue, on retourne quand même la
        # proposition — Oracle pourra au moins la logger en console,
        # mais elle ne sera pas visible dans le CLI tant que Firestore
        # n'est pas accessible.
        print(f"[REMEDIATION] ⚠️ Impossible de persister la proposition : {e}")

    return proposal


def list_pending_proposals() -> list[dict]:
    """Retourne toutes les propositions en attente de confirmation humaine."""
    db = _get_db()
    docs = db.collection(PROPOSALS_COLLECTION).where(
        "status", "==", "pending_human_confirmation"
    ).stream()
    return [doc.to_dict() for doc in docs]


def mark_proposal_status(proposal_id: str, status: str):
    """Met à jour le statut d'une proposition (confirmed / rejected / executed / failed)."""
    db = _get_db()
    db.collection(PROPOSALS_COLLECTION).document(proposal_id).update({
        "status": status,
        "resolved_at": time.time(),
    })


def execute_disable_service_account_key(project_id: str, service_account_email: str, key_id: str) -> bool:
    """
    Désactive une clé de service account. Appelé UNIQUEMENT depuis
    tools/remediate.py, après confirmation humaine explicite.
    """
    try:
        client = iam_admin_v1.IAMClient()
        key_name = (
            f"projects/{project_id}/serviceAccounts/{service_account_email}"
            f"/keys/{key_id}"
        )
        client.disable_service_account_key(name=key_name)
        print(f"[REMEDIATION] ✅ Clé désactivée : {key_name}")
        return True
    except Exception as e:
        print(f"[REMEDIATION] ❌ Échec désactivation clé : {e}")
        return False


def execute_revoke_iam_role(project_id: str, principal: str, role: str) -> bool:
    """
    Retire un rôle IAM d'un principal sur un projet. Appelé UNIQUEMENT
    depuis tools/remediate.py, après confirmation humaine explicite.

    principal doit être au format complet, ex: 'user:x@y.com' ou
    'serviceAccount:x@y.iam.gserviceaccount.com'.
    """
    try:
        client = resourcemanager_v3.ProjectsClient()
        resource = f"projects/{project_id}"

        policy = client.get_iam_policy(request={"resource": resource})

        modified = False
        for binding in policy.bindings:
            if binding.role == role and principal in binding.members:
                binding.members.remove(principal)
                modified = True

        if not modified:
            print(f"[REMEDIATION] ⚠️ Binding introuvable — {principal} n'a pas "
                  f"le rôle {role} sur {resource} (peut-être déjà révoqué).")
            return False

        client.set_iam_policy(request={"resource": resource, "policy": policy})
        print(f"[REMEDIATION] ✅ Rôle {role} révoqué pour {principal}")
        return True
    except Exception as e:
        print(f"[REMEDIATION] ❌ Échec révocation IAM : {e}")
        return False