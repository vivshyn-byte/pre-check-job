import json
import os
import random
import sys
import time
from datetime import datetime
from google.cloud import storage
from google.api_core.exceptions import ResourceExhausted
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig, Tool
from vertexai.preview.generative_models import grounding

from html_formatter import generate_html_content_from_array
from email_send import send_enterprise_email


def load_prompt(file_path="prompt_instructions.md"):
    """Loads the system instructions from a Markdown file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Error: Prompt file '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)

def list_available_models():
    """Lists available Gemini models after configuration."""
    print(f"Fetching available models...")
    try:
        model = GenerativeModel("gemini-2.5-pro")
        print(f"--- Available Gemini Models ---")
        # This is a placeholder as the direct listing is less straightforward.
        # We confirm the model we intend to use is available by instantiating it.
        print(f" - Verified access to: {model.model_name}")
        print("-------------------------------\n")
    except Exception as e:
        print(f"Failed to list models: {e}", file=sys.stderr)

def analyze_report_with_gemini(report_data, project_id, datastore_id, system_instructions):
    """Sends the report and receipts to Gemini for policy evaluation using the GenAI SDK."""
    model_name = "gemini-2.5-pro" # Use a stable, widely available model
    prompt_parts = []
    
    prompt_parts.append(f"{system_instructions}\n\nReport Data:\n{json.dumps(report_data)}")
    
    for entry in report_data.get("expenseEntries", []):
        expense_id = entry.get("expenseId", "Unknown")
        receipt_uri = entry.get("receiptImageReferenceURI")
        mime_type = entry.get("receiptDocumentType", "application/pdf")
        
        if receipt_uri and receipt_uri.startswith("gs://"):
            prompt_parts.append(f"Receipt Image for expenseId: {expense_id}")
            prompt_parts.append(Part.from_uri(uri=receipt_uri, mime_type=mime_type))

    config = GenerationConfig(temperature=0.0)
    tools = None

    if datastore_id:
        if datastore_id.startswith("projects/"):
            datastore_path = datastore_id
        else:
            datastore_path = f"projects/{project_id}/locations/global/collections/default_collection/dataStores/{datastore_id}"
        tools = [
            Tool.from_retrieval(
                grounding.Retrieval(
                    grounding.VertexAISearch(datastore=datastore_path)
                )
            )
        ]

    max_retries = 5
    base_delay = 5.0

    for attempt in range(max_retries + 1):
        try:
            # Instantiate the model. The client configuration is picked up automatically.
            model = GenerativeModel(model_name)
            response = model.generate_content(
                contents=prompt_parts,
                generation_config=config,
                tools=tools
            )
            break
        except ResourceExhausted as e:
            if attempt == max_retries:
                print(f"GenAI SDK API Error: Quota exhausted after {max_retries} retries: {e!r}", file=sys.stderr)
                raise
            sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0.5, 2.0)
            print(f" -> 429 Quota exhausted. Retrying in {sleep_time:.2f}s (attempt {attempt + 1}/{max_retries})...", file=sys.stderr)
            time.sleep(sleep_time)
        except Exception as e:
            print(f"GenAI SDK API Error: {e!r}", file=sys.stderr)
            raise
        
    if not response.candidates or not response.candidates[0].content.parts:
        finish_reason = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
        raise ValueError(f"Gemini returned an empty response. Finish reason: {finish_reason}")

    raw_text = response.text.strip() if response.text else ""
    if not raw_text:
        raise ValueError("Gemini returned empty text content.")
    if raw_text.startswith("```json"):
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        
    return raw_text

def save_batch_results_to_gcs(bucket, batch_results):
    """Saves the aggregated AI results as a single JSON file in the results/ directory."""
    # Use a timestamp to prevent overwriting previous batch runs
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    destination_blob_name = f"results/batch_result_{timestamp}.json"
    
    blob = bucket.blob(destination_blob_name)
    result_json_string = json.dumps(batch_results, indent=2)
    blob.upload_from_string(result_json_string, content_type="application/json")
    
    print(f"\n[SUCCESS] Saved aggregated batch results to gs://{bucket.name}/{destination_blob_name}")

def move_file_to_processed(bucket, source_blob):
    """Moves the processed file from reports/ to processed/ by copying and deleting."""
    destination_blob_name = source_blob.name.replace("reports/", "processed/", 1)
    bucket.copy_blob(source_blob, bucket, destination_blob_name)
    source_blob.delete()
    print(f"    [+] Moved source file to gs://{bucket.name}/{destination_blob_name}")

def save_html_to_gcs(bucket, html_string):
    """Saves the HTML report string as a new file in the results/ directory on GCS."""
    # Use a timestamp to keep filenames unique and aligned with the JSON batch files
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    destination_blob_name = f"results/batch_result_{timestamp}.html"
    
    blob = bucket.blob(destination_blob_name)
    
    # Upload the HTML string directly to GCS with the correct content type
    blob.upload_from_string(html_string, content_type="text/html")
    
    print(f"    [+] Saved HTML report to gs://{bucket.name}/{destination_blob_name}")

def process_pending_reports():
    bucket_name = os.environ.get("BUCKET_NAME")
    directory_path = os.environ.get("BUCKET_DIRECTORY", "reports/")
    
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("REGION", "us-central1")
    datastore_id = os.environ.get("DATASTORE_ID")

    if not bucket_name or not project_id:
        print("Error: BUCKET_NAME and GOOGLE_CLOUD_PROJECT are required.", file=sys.stderr)
        sys.exit(1)

    # Initialize the Vertex AI SDK. It automatically uses the project and location from the environment.
    vertexai.init(project=project_id, location=location)

    current_date_str = datetime.now().astimezone().isoformat()
    raw_instructions = load_prompt()
    system_instructions = raw_instructions.format(current_date=current_date_str)
    batch_results = []
    successfully_processed_blobs = []

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blobs = list(storage_client.list_blobs(bucket_name, prefix=directory_path)) # Convert to list to iterate safely

        print(f"Found {len([b for b in blobs if b.name.endswith('.json')])} pending JSON files.\n")

        for blob in blobs:
            if not blob.name.endswith(".json"):
                continue
            
            print(f"Processing file: {blob.name}")
            report_data = {}
            
            try:
                json_string = blob.download_as_text()
                if not json_string or not json_string.strip():
                    raise ValueError(f"Input file '{blob.name}' is empty (0 bytes).")
                report_data = json.loads(json_string)
                report_id = report_data.get("reportDetails", {}).get("reportId", "UNKNOWN")
                
                print(f" -> Evaluating ReportID: {report_id} with Gemini...")
                
                ai_result_json = analyze_report_with_gemini(
                    report_data, project_id, datastore_id, system_instructions
                )
                print(ai_result_json)
                # Validate and parse JSON, then append to our batch array
                parsed_result = json.loads(ai_result_json)
                batch_results.append(parsed_result)
                successfully_processed_blobs.append(blob)

                # Small delay between reports to avoid burst rate-limit spikes
                time.sleep(1.0)
            except Exception as e:
                error_message = str(e) or repr(e)
                print(f" -> Error processing {blob.name}: {error_message}", file=sys.stderr)

                report_details = report_data.get("reportDetails", {}) if isinstance(report_data, dict) else {}
                expense_entries = report_data.get("expenseEntries", []) if isinstance(report_data, dict) else []
                business_purpose = ""
                if expense_entries and isinstance(expense_entries[0], dict):
                    business_purpose = expense_entries[0].get("businessPurpose", "")
                if not business_purpose and isinstance(report_details, dict):
                    business_purpose = report_details.get("businessPurpose", "UNKNOWN")

                error_entry = {
                    "ReportID": report_details.get("reportNumber") or report_details.get("reportId") or "UNKNOWN",
                    "Report name": report_details.get("name", "UNKNOWN"),
                    "Business purpose": business_purpose or "UNKNOWN",
                    "Owner e-mail": report_details.get("ownerEmail", "UNKNOWN"),
                    "Pre-check date-time": datetime.now().astimezone().isoformat(),
                    "Pre-check result": "Error",
                    "Result Reasoning": error_message
                }
                batch_results.append(error_entry)
                successfully_processed_blobs.append(blob)

        # ---------------------------------------------------------
        # THE COMMIT PHASE: Save all results, THEN move the files
        # ---------------------------------------------------------
        if batch_results:
            # 1. Save the aggregated JSON safely to GCS
            save_batch_results_to_gcs(bucket, batch_results)

            # 2. Try to generate HTML from the in-memory array immediately
            try:
                html_string = generate_html_content_from_array(batch_results)
                save_html_to_gcs(bucket, html_string)
            except Exception as e:
                print(f"Non-fatal error generating HTML: {e}", file=sys.stderr)
            # Send the HTML report via email
            try:
                html_string = generate_html_content_from_array(batch_results)
                subject = "Enterprise Pre-Check Report"
                impersonated_user = os.environ.get("IMPERSONATED_USER")
                recipient = os.environ.get("REPORT_RECIPIENT_EMAIL")
                if not impersonated_user or not recipient:
                    print("Error: IMPERSONATED_USER and REPORT_RECIPIENT_EMAIL must be set for email sending.", file=sys.stderr)
                else:
                    send_enterprise_email(html_string, subject, impersonated_user, recipient)
            except Exception as e:
                print(f"Non-fatal error sending email: {e}", file=sys.stderr)


            # 3. Since the save succeeded, it is now safe to move the files
            print("\nCleaning up processed files...")
            for blob in successfully_processed_blobs:
                move_file_to_processed(bucket, blob)
                pass
        else:
            print("\nNo evaluations completed. No files were moved.")

    except Exception as e:
        print(f"Failed to access bucket: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    process_pending_reports()