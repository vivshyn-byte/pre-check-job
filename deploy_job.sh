#!/bin/bash

# Source environment variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/set_env.sh"

gcloud run jobs deploy "${JOB}" \
  --project "${GOOGLE_CLOUD_PROJECT}" \
  --region "${REGION}" \
  --source . \
  --task-timeout "60m" \
  --service-account "${SERVICE_ACCOUNT}" \
  --set-env-vars "BUCKET_NAME=${BUCKET_NAME}" \
  --set-env-vars "DATASTORE_ID=${DATASTORE_ID}" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}" \
  --set-env-vars "REGION=${REGION}" \
  --set-env-vars "SERVICE_ACCOUNT_FILE=${SERVICE_ACCOUNT_FILE}" \
  --set-env-vars "IMPERSONATED_USER=${IMPERSONATED_USER}" \
  --set-env-vars "^#^REPORT_RECIPIENT_EMAIL=${REPORT_RECIPIENT_EMAIL}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL_UA=${REPORT_RECIPIENT_EMAIL_UA}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL_US=${REPORT_RECIPIENT_EMAIL_US}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL_UK=${REPORT_RECIPIENT_EMAIL_UK}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL_DE=${REPORT_RECIPIENT_EMAIL_DE}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL_SK=${REPORT_RECIPIENT_EMAIL_SK}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL_IN=${REPORT_RECIPIENT_EMAIL_IN}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL_CO=${REPORT_RECIPIENT_EMAIL_CO}" \
  --max-retries 0 \
  --execute-now
