"""
Hydra Cloud Shield — core/audit_log_reader.py
Remplace psutil. Source du signal : les Cloud Audit Logs du projet GCP.

C'est le PREMIER fichier à implémenter réellement — sans lui, aucune box
n'a de données à traiter. Utilise google-cloud-logging.

Fonction principale attendue : fetch_recent_events(lookback_minutes)
-> retourne une liste de dicts normalisés (timestamp, method, resource,
principal, severity) que Scout/Tank/Ghost transforment ensuite en
features.
"""
from datetime import datetime, timedelta, timezone

from google.cloud import logging as cloud_logging

from config.settings import PROJECT_ID, LOG_LOOKBACK_MINUTES, RISKY_LOG_FILTERS

_client = None  # lazy singleton, évite de réinstancier à chaque appel


def _get_client() -> cloud_logging.Client:
    global _client
    if _client is None:
        if not PROJECT_ID:
            raise RuntimeError(
                "GCP_PROJECT_ID non configuré. "
                "Renseigne-le dans .env ou en variable d'environnement."
            )
        _client = cloud_logging.Client(project=PROJECT_ID)
    return _client


def _build_filter(lookback_minutes: int) -> str:
    """Combine la fenêtre temporelle et les filtres à risque (OR entre eux)."""
    since = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    # RFC3339, format attendu par Cloud Logging
    timestamp_filter = f'timestamp >= "{since.isoformat()}"'

    if RISKY_LOG_FILTERS:
        risky_combined = " OR ".join(f"({f})" for f in RISKY_LOG_FILTERS)
        return f'{timestamp_filter} AND ({risky_combined})'
    return timestamp_filter


def _normalize_entry(entry) -> dict:
    """Extrait les champs utiles d'une LogEntry Cloud Logging, en gérant
    le fait que payload peut être un dict (JSON) ou un texte brut."""
    payload = getattr(entry, "payload", None)
    proto_payload = payload if isinstance(payload, dict) else {}

    return {
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "method_name": proto_payload.get("methodName", ""),
        "principal_email": (
            proto_payload.get("authenticationInfo", {}).get("principalEmail", "unknown")
        ),
        "resource_name": proto_payload.get("resourceName", ""),
        "severity": entry.severity if entry.severity else "DEFAULT",
        "log_name": entry.log_name or "",
        "insert_id": entry.insert_id or "",
    }


def fetch_recent_events(lookback_minutes: int = None) -> list[dict]:
    """
    Pull les Cloud Audit Logs récents du projet GCP configuré.

    Retourne une liste de dicts normalisés, vide si rien de neuf depuis
    la fenêtre demandée. Ne lève pas d'exception sur une fenêtre vide —
    seulement sur un vrai problème (projet mal configuré, permissions...).
    """
    lookback_minutes = lookback_minutes or LOG_LOOKBACK_MINUTES
    client = _get_client()
    log_filter = _build_filter(lookback_minutes)

    events = []
    try:
        for entry in client.list_entries(filter_=log_filter, order_by=cloud_logging.DESCENDING):
            events.append(_normalize_entry(entry))
    except Exception as e:
        # On log l'erreur mais on ne fait pas planter la box pour un
        # souci ponctuel de lecture (rate limit, latence API...) —
        # elle retentera au prochain cycle de scan.
        print(f"[AUDIT_LOG_READER] ⚠️ Erreur lors de la lecture des logs : {e}")

    return events


if __name__ == "__main__":
    # Test manuel rapide : python -m core.audit_log_reader
    results = fetch_recent_events(lookback_minutes=60)
    print(f"[AUDIT_LOG_READER] {len(results)} événement(s) trouvé(s) :")
    for r in results[:10]:
        print(f"  • {r['timestamp']} | {r['method_name']} | {r['principal_email']}")