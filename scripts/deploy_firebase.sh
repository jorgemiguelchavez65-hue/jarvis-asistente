#!/usr/bin/env bash
# Despliega Jarvis sin costos fijos de cómputo:
#   Firebase Hosting (app) -> Cloud Run (escala a cero) <- Cloud Tasks (informes)
#   Firestore (visitas) + Cloud Storage (audio temporal) + Secret Manager
# Uso: scripts/deploy_firebase.sh ID_DEL_PROYECTO_FIREBASE
# Requiere: gcloud y firebase CLI con sesión iniciada, y el proyecto en el plan Blaze (facturación activa).
set -euo pipefail

PROJECT="${1:?Uso: $0 ID_DEL_PROYECTO_FIREBASE}"
REGION="${REGION:-us-central1}"   # si cambias la región, cámbiala también en firebase.json
SERVICE="jarvis"                  # debe coincidir con "serviceId" en firebase.json
QUEUE="jarvis-process"
BUCKET="${PROJECT}-jarvis-audio"

gcloud config set project "$PROJECT" >/dev/null
NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
SA="${NUM}-compute@developer.gserviceaccount.com"        # cuenta con la que corre el servicio
SERVICE_URL="https://${SERVICE}-${NUM}.${REGION}.run.app"  # URL determinista de Cloud Run

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudtasks.googleapis.com firestore.googleapis.com

# --- Firestore (visitas) ---
gcloud firestore databases describe >/dev/null 2>&1 || \
  gcloud firestore databases create --location="$REGION" --type=firestore-native

# --- Bucket de audio temporal: lo que se escape de la limpieza normal se borra a los 2 días ---
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file=scripts/lifecycle.json

# --- Cola de Cloud Tasks: hasta 5 intentos con espera creciente ---
QFLAGS=(--max-attempts=5 --min-backoff=60s --max-backoff=600s --max-doublings=3 --max-concurrent-dispatches=2)
if gcloud tasks queues describe "$QUEUE" --location="$REGION" >/dev/null 2>&1; then
  gcloud tasks queues update "$QUEUE" --location="$REGION" "${QFLAGS[@]}"
else
  gcloud tasks queues create "$QUEUE" --location="$REGION" "${QFLAGS[@]}"
fi

# --- Secretos ---
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

# --- Permisos de la cuenta del servicio ---
for s in anthropic-api-key jarvis-token; do
  gcloud secrets add-iam-policy-binding "$s" --member="serviceAccount:$SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done
for role in roles/datastore.user roles/cloudtasks.enqueuer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
    --role="$role" --condition=None >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
  --role=roles/storage.objectUser >/dev/null
# Para crear tareas que se identifican como esa misma cuenta (token OIDC):
gcloud iam service-accounts add-iam-policy-binding "$SA" --member="serviceAccount:$SA" \
  --role=roles/iam.serviceAccountUser >/dev/null

# --- Cloud Run: escala a cero (sin instancia encendida), CPU solo mientras atiende ---
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --min-instances 0 --max-instances 2 --concurrency 4 --cpu 4 --memory 4Gi --timeout 3600 \
  --set-env-vars "JARVIS_BACKEND=gcp,GOOGLE_CLOUD_PROJECT=$PROJECT,JARVIS_AUDIO_BUCKET=$BUCKET,JARVIS_TASKS_QUEUE=$QUEUE,JARVIS_TASKS_LOCATION=$REGION,JARVIS_TASKS_SA=$SA,JARVIS_SERVICE_URL=$SERVICE_URL" \
  --set-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,JARVIS_ACCESS_TOKEN=jarvis-token:latest"

# Si la URL real no coincide con la calculada, se corrige (las tareas se envían a JARVIS_SERVICE_URL).
REAL_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
if [ "$REAL_URL" != "$SERVICE_URL" ]; then
  echo "Ajustando JARVIS_SERVICE_URL a $REAL_URL"
  gcloud run services update "$SERVICE" --region "$REGION" --update-env-vars "JARVIS_SERVICE_URL=$REAL_URL"
fi

# --- Firebase: app del teléfono y reglas de Firestore (cerradas al público) ---
firebase deploy --only hosting,firestore:rules --project "$PROJECT"
echo "Listo: https://$PROJECT.web.app"
