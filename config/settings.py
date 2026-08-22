"""
Hydra Cloud Shield — config/settings.py
Configuration centralisée. Rien de secret ici — les clés/credentials
passent par Secret Manager ou variables d'env, jamais en dur.
"""
import os

# ── Projet GCP ────────────────────────────────────────────────────────────
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")

# ── Pub/Sub (remplace le ring UDP) ───────────────────────────────────────
RING_TOPIC = "hydra-ring"
RING_SUBSCRIPTION_PREFIX = "hydra-ring-sub-"  # + nom du rôle

# ── Firestore (remplace memory.json) ─────────────────────────────────────
MEMORY_COLLECTION = "hydra_memory"

# ── Gemini ────────────────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-3.6-flash"  # requirement hackathon : Gemini 3.5+

# ── Cloud Audit Logs ──────────────────────────────────────────────────────
# Fenêtre de temps scannée à chaque cycle par le Scout
LOG_LOOKBACK_MINUTES = 5

# Filtres de log considérés à risque (point de départ, à affiner)
RISKY_LOG_FILTERS = [
    'protoPayload.methodName="google.iam.admin.v1.CreateServiceAccountKey"',
    'protoPayload.methodName="SetIamPolicy"',
    'severity>=WARNING',
]

# ── Seuils d'alerte (repris du système local) ────────────────────────────
ALERT_THRESHOLD_LOW = 20
ALERT_THRESHOLD_MEDIUM = 40
ALERT_THRESHOLD_HIGH = 70

# ── Cycle des boxes ───────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 30
