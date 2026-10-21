# Expense Reports Pre-Check Job

Automated audit service for employee expense reports powered by Vertex AI Gemini and Google Cloud Run Jobs. The job audits expense JSON reports against corporate policies stored in Vertex AI Search (Data Store), saves evaluated JSON/HTML reports to Cloud Storage, and emails summary digests via Gmail API using Google Workspace Domain-Wide Delegation.

---

## Architecture Overview

1. **Trigger**: Cloud Run Job executed on a schedule (e.g., via Cloud Scheduler) or manually.
2. **Input**: Cloud Storage bucket prefix `reports/*.json`.
3. **Evaluation**: Vertex AI Gemini model grounded with corporate policy documents in Vertex AI Search.
4. **Storage**: Summary results stored as JSON (`results/batch_result_{timestamp}.json`), global HTML (`results/batch_result_{timestamp}.html`), and separate country HTML reports (`results/batch_result_{timestamp}_{COUNTRY}.html`) in `results/` on GCS.
5. **Notification**: Formatted HTML summary sent via Gmail API using Domain-Wide Delegation to `REPORT_RECIPIENT_EMAIL` (global digest) and to country-specific recipients (`REPORT_RECIPIENT_EMAIL_{COUNTRY}`).

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

## Supported Country Mapping

Country names and codes present in report payloads are normalized to standardized country keys for grouping and recipient routing:

| Country Key | Country Name | Environment Recipient Variable |
|---|---|---|
| `UA` | Ukraine | `REPORT_RECIPIENT_EMAIL_UA` |
| `US` | United States | `REPORT_RECIPIENT_EMAIL_US` |
| `UK` | United Kingdom | `REPORT_RECIPIENT_EMAIL_UK` |
| `DE` | Germany | `REPORT_RECIPIENT_EMAIL_DE` |
| `SK` | Slovakia | `REPORT_RECIPIENT_EMAIL_SK` |
| `IN` | India | `REPORT_RECIPIENT_EMAIL_IN` |
| `CO` | Colombia | `REPORT_RECIPIENT_EMAIL_CO` |

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
| `REPORT_RECIPIENT_EMAIL_{COUNTRY}` | No | Country-specific AP email recipient (e.g. `REPORT_RECIPIENT_EMAIL_UA`, `_US`, `_UK`, `_DE`, `_SK`, `_IN`, `_CO`) | `ap-ua@astounddigital.com` |
| `JOB` | No | Cloud Run job resource name | `expense-precheck-job` |
| `SERVICE_ACCOUNT_FILE` | Optional* | File path to SA key JSON | `/secrets/sa-key.json` |
| `SERVICE_ACCOUNT_INFO` | Optional* | Stringified JSON of SA private key | `{"type": "service_account", ...}` |

\* Either `SERVICE_ACCOUNT_FILE` or `SERVICE_ACCOUNT_INFO` must be set for Domain-Wide Delegation.

---

## Deployment

The project includes `set_env.sh` and `deploy_job.sh` for configuring environment variables and deploying the job to Cloud Run directly using source-based deployment:

1. **Configure environment settings** in `set_env.sh`:
   ```bash
   export GOOGLE_CLOUD_PROJECT="<YOUR_PROJECT_ID>"
   export REGION="us-central1"
   export BUCKET_NAME="reports_to_check"
   export DATASTORE_ID="<YOUR_DATASTORE_ID>"
   export SERVICE_ACCOUNT="<YOUR_SA_EMAIL>"
   export IMPERSONATED_USER="<SENDER_EMAIL>"
   export REPORT_RECIPIENT_EMAIL="<GLOBAL_RECIPIENTS>"
   export REPORT_RECIPIENT_EMAIL_UA="ap-ua@company.com"
   export REPORT_RECIPIENT_EMAIL_US="ap-na@company.com"
   export REPORT_RECIPIENT_EMAIL_UK="ap-uk@company.com"
   export REPORT_RECIPIENT_EMAIL_DE="ap-ge@company.com"
   export REPORT_RECIPIENT_EMAIL_SK="ap-sk@company.com"
   export REPORT_RECIPIENT_EMAIL_IN="ap-ind@company.com"
   export REPORT_RECIPIENT_EMAIL_CO="ap-co@company.com"
   export SERVICE_ACCOUNT_FILE="<PATH_TO_SA_KEY_JSON>"
   export JOB="expense-precheck-job"
   ```

2. **Deploy and run the job**:
   ```bash
   chmod +x set_env.sh deploy_job.sh
   ./deploy_job.sh
   ```

`deploy_job.sh` builds the container image from local source via Google Cloud Build and provisions the Cloud Run job:

```bash
gcloud run jobs deploy "${JOB}" \
    --project "${GOOGLE_CLOUD_PROJECT}" \
    --region="${REGION}" \
    --source . \
    --task-timeout "60m" \
    --service-account "${SERVICE_ACCOUNT}" \
    --max-retries 0 \
    --execute-now
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