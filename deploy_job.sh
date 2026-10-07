#!/bin/bash

# Source environment variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/set_env.sh"

gcloud run jobs deploy "${JOB}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --source . \
  --task-timeout "15m" \
  --service-account "${SERVICE_ACCOUNT}" \
  --set-env-vars "BUCKET_NAME=${BUCKET_NAME}" \
  --set-env-vars "DATASTORE_ID=${DATASTORE_ID}" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}" \
  --set-env-vars "REGION=${REGION}" \
  --set-env-vars "SERVICE_ACCOUNT_FILE=${SERVICE_ACCOUNT_FILE}" \
  --set-env-vars "IMPERSONATED_USER=${IMPERSONATED_USER}" \
  --set-env-vars "^#^REPORT_RECIPIENT_EMAIL=${REPORT_RECIPIENT_EMAIL}" \
  --max-retries 0 \
  --execute-now
