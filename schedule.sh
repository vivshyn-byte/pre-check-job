#!/bin/bash

PROJECT_ID="finance-concur"
REGION="us-central1"
SERVICE_ACCOUNT="receipt-processor-sa@finance-concur.iam.gserviceaccount.com"
JOB_NAME="expense-precheck-job"
SCHEDULER_NAME="expense-precheck-trigger"


# 2. Grant the Service Account permission to trigger the job (Only needed once, but safe to run repeatedly)
echo "Ensuring invoker permissions..."
gcloud run jobs add-iam-policy-binding $JOB_NAME \
    --region $REGION \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker"

# 3. Create or Update the Cloud Scheduler Job
echo "Configuring Cloud Scheduler..."
if gcloud scheduler jobs describe $SCHEDULER_NAME --location $REGION >/dev/null 2>&1; then
    # Update existing schedule
    gcloud scheduler jobs update http $SCHEDULER_NAME \
        --location $REGION \
        --schedule "0 9 * * *" \
        --time-zone "UTC" \
        --uri "https://${REGION}-run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run" \
        --oauth-service-account-email=$SERVICE_ACCOUNT
else
    # Create new schedule
    gcloud scheduler jobs create http $SCHEDULER_NAME \
        --location $REGION \
        --schedule "0 9 * * *" \
        --time-zone "UTC" \
        --uri "https://${REGION}-run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run" \
        --http-method POST \
        --oauth-service-account-email=$SERVICE_ACCOUNT
fi

echo "Deployment and scheduling complete!"