#!/usr/bin/env bash
# Despliega Jarvis: API en Cloud Run + app del teléfono en Firebase Hosting.
# Uso: scripts/deploy_firebase.sh ID_DEL_PROYECTO_FIREBASE
# Requiere: gcloud y firebase CLI con sesión iniciada, y el proyecto en el plan Blaze (facturación activa).
set -euo pipefail

PROJECT="${1:?Uso: $0 ID_DEL_PROYECTO_FIREBASE}"
REGION="${REGION:-us-central1}"   # si cambias la región, cámbiala también en firebase.json
SERVICE="jarvis"                  # debe coincidir con "serviceId" en firebase.json
BUCKET="${PROJECT}-jarvis-data"

gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com

# Bucket para los datos: Cloud Run no tiene disco permanente.
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access

put_secret() {  # nombre, valor
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    printf %s "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
  else
    printf %s "$2" | gcloud secrets create "$1" --data-file=- >/dev/null
  fi
}

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then read -rsp "ANTHROPIC_API_KEY: " ANTHROPIC_API_KEY; echo; fi
put_secret anthropic-api-key "$ANTHROPIC_API_KEY"
if ! gcloud secrets describe jarvis-token >/dev/null 2>&1; then
  TOKEN="$(openssl rand -base64 24 | tr '+/' '-_' | tr -d '=')"
  put_secret jarvis-token "$TOKEN"
  echo "Contraseña de la app (guárdala, no se vuelve a mostrar): $TOKEN"
fi

# Permisos de la cuenta con la que corre el servicio.
NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
SA="${NUM}-compute@developer.gserviceaccount.com"
for s in anthropic-api-key jarvis-token; do
  gcloud secrets add-iam-policy-binding "$s" --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
  --role=roles/storage.objectUser >/dev/null

# Una sola instancia siempre encendida y con CPU permanente: el informe se genera en segundo plano.
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --execution-environment gen2 --cpu 2 --memory 4Gi \
  --min-instances 1 --max-instances 1 --no-cpu-throttling \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,JARVIS_ACCESS_TOKEN=jarvis-token:latest" \
  --add-volume "name=data,type=cloud-storage,bucket=$BUCKET" \
  --add-volume-mount "volume=data,mount-path=/data"

firebase deploy --only hosting --project "$PROJECT"
echo "Listo: https://$PROJECT.web.app"
