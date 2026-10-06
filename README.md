# Expense Reports Pre-Check Job

Automated audit service for employee expense reports powered by Vertex AI Gemini and Google Cloud Run Jobs. The job audits expense JSON reports against corporate policies stored in Vertex AI Search (Data Store), saves evaluated JSON/HTML reports to Cloud Storage, and emails summary digests via Gmail API using Google Workspace Domain-Wide Delegation.

---

## Architecture Overview

1. **Trigger**: Cloud Run Job executed on a schedule (e.g., via Cloud Scheduler) or manually.
2. **Input**: Cloud Storage bucket prefix `reports/*.json`.
3. **Evaluation**: Vertex AI Gemini model grounded with corporate policy documents in Vertex AI Search.
4. **Storage**: Summary results stored as JSON and HTML files in `results/` on GCS.
5. **Notification**: Formatted HTML summary sent via Gmail API using Domain-Wide Delegation.

---

## Prerequisites

### 1. Google Cloud Environment Setup

* A GCP Project with billing enabled.
* `gcloud` CLI installed and authenticated (`gcloud auth login`).
* Required APIs enabled:
  ```bash
  gcloud services enable \
      run.googleapis.com \
      artifactregistry.googleapis.com \
      cloudbuild.googleapis.com \
      aiplatform.googleapis.com \
      discoveryengine.googleapis.com \
      storage.googleapis.com \
      gmail.googleapis.com \
      secretmanager.googleapis.com
  ```

### 2. Service Accounts & IAM Permissions

You will need a dedicated Service Account for the job:

1. Create the Service Account:
   ```bash
   export PROJECT_ID="<YOUR_GCP_PROJECT_ID>"
   export SA_NAME="expense-precheck-sa"
   export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

   gcloud iam service-accounts create ${SA_NAME} \
       --display-name="Expense Pre-check Job Service Account"
   ```

2. Assign Required GCP IAM Roles:
   * **Vertex AI User**: `roles/aiplatform.user`
   * **Discovery Engine Viewer** (for Vertex AI Search Grounding): `roles/discoveryengine.viewer`
   * **Storage Object Admin**: `roles/storage.objectAdmin` (on your reports GCS bucket)
   * **Secret Manager Secret Accessor** (if storing SA keys in Secret Manager): `roles/secretmanager.secretAccessor`

   ```bash
   gcloud projects add-iam-policy-binding ${PROJECT_ID} \
       --member="serviceAccount:${SA_EMAIL}" \
       --role="roles/aiplatform.user"

   gcloud projects add-iam-policy-binding ${PROJECT_ID} \
       --member="serviceAccount:${SA_EMAIL}" \
       --role="roles/discoveryengine.viewer"
   ```

### 3. Google Workspace Domain-Wide Delegation (DWD)

Because the service sends emails on behalf of a Google Workspace user via the Gmail API, Domain-Wide Delegation is required:

1. Generate a JSON key for the Service Account:
   ```bash
   gcloud iam service-accounts keys create sa-key.json \
       --iam-account=${SA_EMAIL}
   ```
2. Note the **Client ID** (OAuth 2 Client ID) of the service account:
   ```bash
   gcloud iam service-accounts describe ${SA_EMAIL} --format="value(oauth2ClientId)"
   ```
3. Log in to the Google Workspace Admin Console as a Super Admin:
   * Navigate to **Security** > **Access and data control** > **API controls**.
   * Select **Manage Domain-Wide Delegation**.
   * Click **Add new** and enter:
     * **Client ID**: The numeric OAuth 2 Client ID copied above.
     * **OAuth Scopes**: `https://www.googleapis.com/auth/gmail.send`
   * Click **Authorize**.

---

## Environment Variables

| Variable | Required | Description | Example |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | Yes | Target Google Cloud Project ID | `my-corp-project` |
| `REGION` | No | Vertex AI / Cloud Run region | `us-central1` (default) |
| `BUCKET_NAME` | Yes | GCS Bucket containing reports | `my-expense-reports-bucket` |
| `BUCKET_DIRECTORY` | No | Path prefix inside the bucket | `reports/` (default) |
| `DATASTORE_ID` | No | Vertex AI Search Datastore ID or full resource path | `expense-policies-ds` |
| `IMPERSONATED_USER` | Yes | Workspace email to send from | `finance-audit@company.com` |
| `REPORT_RECIPIENT_EMAIL` | Yes | Email recipient for summary report | `audit-team@company.com` |
| `SERVICE_ACCOUNT_FILE` | Optional* | File path to SA key JSON | `/secrets/sa-key.json` |
| `SERVICE_ACCOUNT_INFO` | Optional* | Stringified JSON of SA private key | `{"type": "service_account", ...}` |

\* Either `SERVICE_ACCOUNT_FILE` or `SERVICE_ACCOUNT_INFO` must be set for Domain-Wide Delegation.

---

## Deployment Script

Create a deployment shell script (`deploy.sh`) to automate container building and Cloud Run Job deployment:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Configuration
PROJECT_ID="<YOUR_GCP_PROJECT_ID>"
REGION="us-central1"
JOB_NAME="expense-precheck-job"
REPOSITORY="pre-check-repo"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${JOB_NAME}:latest"
SA_EMAIL="expense-precheck-sa@${PROJECT_ID}.iam.gserviceaccount.com"

BUCKET_NAME="<YOUR_EXPENSE_BUCKET>"
DATASTORE_ID="<YOUR_DATASTORE_ID>"
IMPERSONATED_USER="<SENDER_EMAIL@YOUR_DOMAIN.COM>"
REPORT_RECIPIENT_EMAIL="<RECIPIENT_EMAIL@YOUR_DOMAIN.COM>"
SECRET_NAME="gmail-dwd-sa-key"

echo "==> Configuring gcloud project..."
gcloud config set project "${PROJECT_ID}"

echo "==> Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories describe "${REPOSITORY}" --location="${REGION}" >/dev/null 2>&1 || \
gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Docker repository for expense precheck job"

echo "==> Building and pushing container image via Cloud Build..."
gcloud builds submit --tag "${IMAGE_NAME}" .

echo "==> Storing SA Key into Secret Manager (if not present)..."
if ! gcloud secrets describe "${SECRET_NAME}" >/dev/null 2>&1; then
    gcloud secrets create "${SECRET_NAME}" --data-file=sa-key.json
    gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor"
fi

echo "==> Deploying Cloud Run Job..."
gcloud run jobs deploy "${JOB_NAME}" \
    --image="${IMAGE_NAME}" \
    --region="${REGION}" \
    --service-account="${SA_EMAIL}" \
    --set-env-vars="BUCKET_NAME=${BUCKET_NAME},GOOGLE_CLOUD_PROJECT=${PROJECT_ID},REGION=${REGION},DATASTORE_ID=${DATASTORE_ID},IMPERSONATED_USER=${IMPERSONATED_USER},REPORT_RECIPIENT_EMAIL=${REPORT_RECIPIENT_EMAIL},SERVICE_ACCOUNT_FILE=/secrets/sa-key.json" \
    --set-secrets="/secrets/sa-key.json=${SECRET_NAME}:latest" \
    --max-retries=0 \
    --task-timeout=30m

echo "==> Deployment successful!"
echo "To execute the job manually, run:"
echo "    gcloud run jobs execute ${JOB_NAME} --region=${REGION}"
```

---

## Executing and Scheduling

* **Manual Execution**:
  ```bash
  gcloud run jobs execute expense-precheck-job --region=us-central1
  ```
* **Scheduled Execution** (Cloud Scheduler runs daily at 08:00 AM UTC):
  ```bash
  gcloud scheduler jobs create http expense-precheck-scheduler \
      --location=us-central1 \
      --schedule="0 8 * * *" \
      --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/expense-precheck-job:run" \
      --http-method=POST \
      --oauth-service-account-email="${SA_EMAIL}"
  ```