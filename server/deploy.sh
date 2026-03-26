#!/bin/bash
set -euo pipefail

PROJECT="covenance-469421"
REGION="europe-west1"
SERVICE="gleaner"
BUCKET="gleaner-sessions"

echo "=== Deploying Gleaner to Cloud Run ==="

# Create GCS bucket if it doesn't exist
if ! gsutil ls "gs://$BUCKET" &>/dev/null; then
    echo "Creating GCS bucket gs://$BUCKET..."
    gsutil mb -p "$PROJECT" -l "$REGION" "gs://$BUCKET"
fi

# Preserve existing admin token across deploys
ADMIN_TOKEN=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format=json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for e in d['spec']['template']['spec']['containers'][0].get('env', []):
        if e['name'] == 'GLEANER_ADMIN_TOKEN':
            print(e['value'])
            break
except Exception:
    pass
" 2>/dev/null || true)
ENV_VARS="GLEANER_GCP_PROJECT=$PROJECT,GLEANER_GCS_BUCKET=$BUCKET"
if [ -n "$ADMIN_TOKEN" ]; then
    ENV_VARS="$ENV_VARS,GLEANER_ADMIN_TOKEN=$ADMIN_TOKEN"
    echo "Preserving existing admin token"
fi

# Deploy to Cloud Run from source
echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT" \
    --region "$REGION" \
    --allow-unauthenticated \
    --memory 256Mi \
    --min-instances 0 \
    --max-instances 3 \
    --set-env-vars "$ENV_VARS"

# Get the service URL
URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')
echo ""
echo "=== Deployed! ==="
echo "URL: $URL"
echo ""
echo "Next steps:"
echo "  1. Set admin token:  gcloud run services update $SERVICE --region $REGION --set-env-vars GLEANER_ADMIN_TOKEN=\$(openssl rand -hex 32)"
echo "  2. Create a user token via admin API"
echo "  3. Configure clients with GLEANER_URL=$URL and GLEANER_TOKEN=<token>"
