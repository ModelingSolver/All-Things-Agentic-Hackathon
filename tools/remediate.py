"""
Hydra Cloud Shield — tools/remediate.py
CLI de confirmation humaine — le SEUL point d'entrée légitime pour
exécuter une action de remédiation IAM réelle.

Aucune box n'appelle jamais execute_disable_service_account_key ou
execute_revoke_iam_role directement. Oracle se contente de PROPOSER
(core.remediation.propose), ce qui persiste la proposition dans
Firestore avec le statut "pending_human_confirmation". Ce script lit
ces propositions, les affiche, et n'exécute l'action réelle qu'après
une confirmation explicite [y/N] tapée par un humain.

Usage :
    python -m tools.remediate
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import remediation
from config.settings import PROJECT_ID


def _print_proposal(p: dict, index: int):
    print(f"\n{'─' * 60}")
    print(f"  [{index}] Proposition #{p['proposal_id']}")
    print(f"{'─' * 60}")
    print(f"  Identité       : {p['identity']}")
    print(f"  Verdict        : {p['verdict']} (score {p['score']}/100)")
    print(f"  Explication    : {p['explanation']}")
    print(f"  Action prévue  : {p['recommended_action']}")


def _handle_action(p: dict) -> bool:
    """Exécute l'action recommandée pour une proposition, retourne
    True si l'exécution a réussi (ou si l'humain a explicitement
    refusé — dans ce cas on considère le traitement 'terminé', pas
    'échoué')."""
    action = p.get("recommended_action")

    if action == "disable_service_account_key":
        identity = p["identity"]
        print(f"\n  ⚠️  Cette action va DÉSACTIVER une clé de service account pour : {identity}")
        key_id = input("  Entre l'ID de la clé à désactiver (ou vide pour annuler) : ").strip()
        if not key_id:
            print("  ⏭️  Annulé, aucune clé désactivée.")
            return False
        return remediation.execute_disable_service_account_key(PROJECT_ID, identity, key_id)

    elif action == "revoke_iam_role":
        identity = p["identity"]
        print(f"\n  ⚠️  Cette action va RÉVOQUER un rôle IAM pour : {identity}")
        role = input("  Entre le rôle exact à révoquer (ex: roles/editor) : ").strip()
        if not role:
            print("  ⏭️  Annulé, aucun rôle révoqué.")
            return False
        principal = identity if ":" in identity else f"user:{identity}"
        return remediation.execute_revoke_iam_role(PROJECT_ID, principal, role)

    else:
        print(f"  ℹ️  Action recommandée '{action}' — pas d'exécution automatisable, "
              f"traite manuellement si nécessaire.")
        return True


def main():
    if not PROJECT_ID:
        print("❌ GCP_PROJECT_ID non configuré. Voir .env.example.")
        sys.exit(1)

    print("🛡️  Hydra Cloud Shield — Console de remédiation humaine")
    print(f"   Projet : {PROJECT_ID}\n")

    proposals = remediation.list_pending_proposals()

    if not proposals:
        print("✅ Aucune proposition en attente. La ruche n'a rien signalé de critique.")
        return

    print(f"📋 {len(proposals)} proposition(s) en attente de confirmation :")

    for i, p in enumerate(proposals, start=1):
        _print_proposal(p, i)

        choice = input(
            "\n  [E]xécuter  [I]gnorer  [S]kip pour l'instant  > "
        ).strip().lower()

        if choice == "e":
            confirm = input(
                f"  ⚠️  Confirme : exécuter '{p['recommended_action']}' pour "
                f"{p['identity']} ? Tape 'CONFIRMER' en toutes lettres : "
            ).strip()
            if confirm == "CONFIRMER":
                success = _handle_action(p)
                remediation.mark_proposal_status(
                    p["proposal_id"], "executed" if success else "failed"
                )
            else:
                print("  ⏭️  Confirmation non reçue, action annulée.")
                remediation.mark_proposal_status(p["proposal_id"], "skipped")

        elif choice == "i":
            remediation.mark_proposal_status(p["proposal_id"], "rejected")
            print("  🗑️  Proposition rejetée, pas d'action prise.")

        else:
            print("  ⏭️  Laissée en attente pour plus tard.")

    print("\n✅ Session de remédiation terminée.")


if __name__ == "__main__":
    main()