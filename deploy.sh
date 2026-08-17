#!/bin/bash
# Hydra Cloud Shield — deploy.sh
# Déploie le même conteneur 5 fois, un par rôle (BOX_ROLE en env var).
# TODO: remplir PROJECT_ID avant utilisation.

set -e

PROJECT_ID="TON_PROJECT_ID_ICI"
REGION="europe-west1"
IMAGE="gcr.io/${PROJECT_ID}/hydra-cloud"

echo "[DEPLOY] Build de l'image..."
gcloud builds submit --tag "${IMAGE}" --project "${PROJECT_ID}"

ROLES=("scout" "tank" "ghost" "oracle" "druid")

for ROLE in "${ROLES[@]}"; do
  echo "[DEPLOY] Déploiement de hydra-${ROLE}..."
  gcloud run deploy "hydra-${ROLE}" \
    --image "${IMAGE}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --set-env-vars "BOX_ROLE=${ROLE},GCP_PROJECT_ID=${PROJECT_ID}" \
    --no-allow-unauthenticated \
    --min-instances=1 \
    --max-instances=1
done

echo "[DEPLOY] ✅ 5 boxes déployées."