#!/bin/bash


export PROJECT_ID="finance-concur"
export REGION="us-central1"
export BUCKET_NAME="reports_to_check"
export DATASTORE_ID="expense-policy_1789124227073_gcs_store"
export SERVICE_ACCOUNT="receipt-processor-sa@finance-concur.iam.gserviceaccount.com"
export IMPERSONATED_USER="v.ivshyn@astounddigital.com"
export REPORT_RECIPIENT_EMAIL="v.ivshyn@astounddigital.com"
export SERVICE_ACCOUNT_FILE="finance-concur-251320b8ec47.json"
export RECIPIENT_EMAIL="v.ivshyn@astounddigital.com"
export IMPERSONATED_USER="v.ivshyn@astounddigital.com"
export JOB="expense-precheck-job"
export REGION="us-central1"



gcloud run jobs deploy expense-precheck-job \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --source . \
  --task-timeout "15m" \
  --service-account "${SERVICE_ACCOUNT}" \
  --set-env-vars "BUCKET_NAME=${BUCKET_NAME}" \
  --set-env-vars "DATASTORE_ID=${DATASTORE_ID}" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID}" \
  --set-env-vars "REGION=${REGION}" \
  --set-env-vars "SERVICE_ACCOUNT_FILE=${SERVICE_ACCOUNT_FILE}" \
  --set-env-vars "IMPERSONATED_USER=${IMPERSONATED_USER}" \
  --set-env-vars "REPORT_RECIPIENT_EMAIL=${REPORT_RECIPIENT_EMAIL}" \
  --max-retries 0 \
  --execute-now \
  