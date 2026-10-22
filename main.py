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
from datetime import datetime, timezone
from html_formatter import generate_html_content_from_array, group_records_by_country, sanitize_country_code
from excel_formatter import generate_excel_from_array, save_excel_to_gcs
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
        model = GenerativeModel("gemini-2.5-pro")  # Attempt to instantiate a known model
        print(f"--- Available Gemini Models ---")
        # This is a placeholder as the direct listing is less straightforward.
        # We confirm the model we intend to use is available by instantiating it.
        print(f" - Verified access to: {model.model_name}")
        print("-------------------------------\n")
    except Exception as e:
        print(f"Failed to list models: {e}", file=sys.stderr)

MIME_TYPE_MAP = {
    "pdf": "application/pdf",
    "application/pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/jpeg": "image/jpeg",
    "png": "image/png",
    "image/png": "image/png",
    "webp": "image/webp",
    "image/webp": "image/webp",
    "heic": "image/heic",
    "image/heic": "image/heic",
    "heif": "image/heif",
    "image/heif": "image/heif",
    "gif": "image/gif",
    "image/gif": "image/gif",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "image/tiff": "image/tiff",
}


def resolve_receipt_mime_type(receipt_uri, raw_mime_type=None):
    """Resolves and normalizes the MIME type for a receipt document or image.

    Guarantees a valid, non-empty MIME type for Gemini Part.from_uri.
    Handles empty strings, None, whitespace, common abbreviations (e.g. 'pdf', 'jpg'),
    and infers from file extension if raw_mime_type is missing or ambiguous.
    """
    cleaned_type = str(raw_mime_type or "").strip().lower()

    if cleaned_type in MIME_TYPE_MAP:
        return MIME_TYPE_MAP[cleaned_type]

    # If MIME type is missing or generic, infer from URI extension
    if not cleaned_type or cleaned_type in ["application/octet-stream", "binary/octet-stream", "unknown", "null"]:
        if receipt_uri:
            clean_path = receipt_uri.split("?")[0].split("#")[0].lower()
            for ext, mtype in [
                (".pdf", "application/pdf"),
                (".jpg", "image/jpeg"),
                (".jpeg", "image/jpeg"),
                (".png", "image/png"),
                (".webp", "image/webp"),
                (".heic", "image/heic"),
                (".heif", "image/heif"),
                (".gif", "image/gif"),
                (".tif", "image/tiff"),
                (".tiff", "image/tiff"),
            ]:
                if clean_path.endswith(ext):
                    return mtype

    if "/" in cleaned_type and not cleaned_type.endswith("/"):
        return cleaned_type

    # Default fallback to application/pdf so mimeType is never empty
    return "application/pdf"


def analyze_report_with_gemini(report_data, project_id, datastore_id, system_instructions):
    """Sends the report and receipts to Gemini for policy evaluation using the GenAI SDK."""
    model_name = "gemini-2.5-pro" # Use a stable, widely available model
    text_prompt = f"{system_instructions}\n\nReport Data:\n{json.dumps(report_data)}"
    prompt_parts = [text_prompt]

    receipt_parts = []
    for entry in report_data.get("expenseEntries", []):
        expense_id = entry.get("expenseId", "Unknown")
        receipt_uri = entry.get("receiptImageReferenceURI")
        raw_doc_type = entry.get("receiptDocumentType")

        if receipt_uri and receipt_uri.startswith("gs://"):
            mime_type = resolve_receipt_mime_type(receipt_uri, raw_doc_type)
            receipt_parts.append(f"Receipt Image for expenseId: {expense_id}")
            receipt_parts.append(Part.from_uri(uri=receipt_uri, mime_type=mime_type))

    prompt_parts.extend(receipt_parts)

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
    current_parts = list(prompt_parts)
    has_receipts = bool(receipt_parts)

    for attempt in range(max_retries + 1):
        try:
            # Instantiate the model. The client configuration is picked up automatically.
            model = GenerativeModel(model_name)
            response = model.generate_content(
                contents=current_parts,
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
            err_str = str(e)
            # If an invalid argument or bad image error occurs on receipt attachments,
            # retry without receipt images so the report data itself can still be evaluated.
            if has_receipts and any(k in err_str for k in ["mimeType", "fileData", "image", "media", "InvalidArgument", "400"]):
                print(f" -> Warning: Failed with receipt attachments ({e!r}). Retrying with text-only evaluation...", file=sys.stderr)
                current_parts = [text_prompt]
                has_receipts = False
                continue

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

def save_batch_results_to_gcs(bucket, batch_results, timestamp=None):
    """Saves the aggregated AI results as a single JSON file in the results/ directory."""
    if not timestamp:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    destination_blob_name = f"results/batch_result_{timestamp}.json"

    blob = bucket.blob(destination_blob_name)
    result_json_string = json.dumps(batch_results, indent=2)
    blob.upload_from_string(result_json_string, content_type="application/json")

    print(f"\n[SUCCESS] Saved aggregated batch results to gs://{bucket.name}/{destination_blob_name}")
    return destination_blob_name

def move_file_to_processed(bucket, source_blob):
    """Moves the processed file from reports/ to processed/ by copying and deleting."""
    destination_blob_name = source_blob.name.replace("reports/", "processed/", 1)
    bucket.copy_blob(source_blob, bucket, destination_blob_name)
    source_blob.delete()
    print(f"    [+] Moved source file to gs://{bucket.name}/{destination_blob_name}")

def save_html_to_gcs(bucket, html_string, timestamp=None, country=None, destination_blob_name=None):
    """Saves the HTML report string as a new file in the results/ directory on GCS.

    Can save global reports (default) or country-scoped reports when country is provided.
    """
    if not destination_blob_name:
        if not timestamp:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if country:
            country_suffix = sanitize_country_code(country)
            destination_blob_name = f"results/batch_result_{timestamp}_{country_suffix}.html"
        else:
            destination_blob_name = f"results/batch_result_{timestamp}.html"

    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(html_string, content_type="text/html")

    label = f" ({country})" if country else " (global)"
    print(f"    [+] Saved HTML report{label} to gs://{bucket.name}/{destination_blob_name}")
    return destination_blob_name

def get_country_recipient_email(country_key):
    """Retrieves the recipient email configured for a given country key from environment variables.

    Looks for REPORT_RECIPIENT_EMAIL_{COUNTRY_KEY} (e.g. REPORT_RECIPIENT_EMAIL_UA).
    """
    if not country_key:
        return None
    code = sanitize_country_code(country_key)
    env_var_name = f"REPORT_RECIPIENT_EMAIL_{code.upper()}"
    recipient = os.environ.get(env_var_name)
    if not recipient and code != country_key.upper():
        recipient = os.environ.get(f"REPORT_RECIPIENT_EMAIL_{country_key.upper()}")
    return recipient

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
                report_details = report_data.get("reportDetails", {}) if isinstance(report_data, dict) else {}
                parsed_result["Country"] = report_details.get("country", "")
                expense_entries = report_data.get("expenseEntries", []) if isinstance(report_data, dict) else []
                parsed_result["expense_purposes"] = {
                    str(entry.get("expenseId")): entry.get("businessPurpose", "")
                    for entry in expense_entries
                    if isinstance(entry, dict) and entry.get("expenseId")
                }
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
                    "Country": report_details.get("country", "UNKNOWN"),
                    "Business purpose": business_purpose or "UNKNOWN",
                    "Owner e-mail": report_details.get("ownerEmail", "UNKNOWN"),
                    "Pre-check date-time": datetime.now().astimezone().isoformat(),
                    "Pre-check result": "Error",
                    "Result Reasoning": error_message,
                    "expense_purposes": {
                        str(entry.get("expenseId")): entry.get("businessPurpose", "")
                        for entry in expense_entries
                        if isinstance(entry, dict) and entry.get("expenseId")
                    }
                }
                batch_results.append(error_entry)

        # ---------------------------------------------------------
        # THE COMMIT PHASE: Save all results, THEN move the files
        # ---------------------------------------------------------
        if batch_results:
            batch_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            formatted_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            # 1. Save the aggregated JSON safely to GCS
            save_batch_results_to_gcs(bucket, batch_results, timestamp=batch_timestamp)

            # 2. Generate and save global HTML report to GCS
            global_html_string = None
            try:
                global_html_string = generate_html_content_from_array(batch_results, current_time=formatted_time)
                save_html_to_gcs(bucket, global_html_string, timestamp=batch_timestamp)
            except Exception as e:
                print(f"Non-fatal error generating/saving global HTML: {e}", file=sys.stderr)

            # 3. Generate and save global Excel spreadsheet report to GCS
            try:
                global_excel_bytes = generate_excel_from_array(batch_results, current_time=formatted_time)
                save_excel_to_gcs(bucket, global_excel_bytes, timestamp=batch_timestamp)
            except Exception as e:
                print(f"Non-fatal error generating/saving global Excel: {e}", file=sys.stderr)

            # 4. Generate and save separate country HTML and Excel reports to GCS
            country_groups = {}
            try:
                country_groups = group_records_by_country(batch_results)
                print(f"\nGenerating country-specific reports for {len(country_groups)} country group(s)...")
                for country_key, group_info in sorted(country_groups.items()):
                    c_display = group_info["display_name"]
                    c_records = group_info["records"]
                    try:
                        c_html = generate_html_content_from_array(
                            c_records,
                            country=c_display,
                            current_time=formatted_time
                        )
                        save_html_to_gcs(
                            bucket,
                            c_html,
                            timestamp=batch_timestamp,
                            country=country_key
                        )
                    except Exception as country_err:
                        print(f"Non-fatal error generating/saving HTML report for country '{country_key}': {country_err}", file=sys.stderr)

                    try:
                        c_excel = generate_excel_from_array(
                            c_records,
                            country=c_display,
                            current_time=formatted_time
                        )
                        save_excel_to_gcs(
                            bucket,
                            c_excel,
                            timestamp=batch_timestamp,
                            country=country_key
                        )
                    except Exception as country_excel_err:
                        print(f"Non-fatal error generating/saving Excel report for country '{country_key}': {country_excel_err}", file=sys.stderr)
            except Exception as e:
                print(f"Non-fatal error grouping records by country: {e}", file=sys.stderr)

            # 5. Email notifications
            impersonated_user = os.environ.get("IMPERSONATED_USER")
            if not impersonated_user:
                print("Error: IMPERSONATED_USER must be set for email sending.", file=sys.stderr)
            else:
                # 4a. Send global HTML report via email
                try:
                    global_recipient = os.environ.get("REPORT_RECIPIENT_EMAIL")
                    if not global_recipient:
                        print("Notice: REPORT_RECIPIENT_EMAIL is not set. Skipping global email sending.", file=sys.stderr)
                    else:
                        if not global_html_string:
                            global_html_string = generate_html_content_from_array(batch_results, current_time=formatted_time)
                        global_subject = "Enterprise Pre-Check Report"
                        send_enterprise_email(global_html_string, global_subject, impersonated_user, global_recipient)
                except Exception as e:
                    print(f"Non-fatal error sending global email: {e}", file=sys.stderr)

                # 4b. Send country-specific HTML reports via email
                for country_key, group_info in sorted(country_groups.items()):
                    try:
                        country_recipient = get_country_recipient_email(country_key)
                        c_display = group_info["display_name"]
                        if not country_recipient:
                            print(f"    [*] No email recipient configured for country '{country_key}' (REPORT_RECIPIENT_EMAIL_{country_key}). Skipping country email.")
                            continue

                        c_records = group_info["records"]
                        c_html = generate_html_content_from_array(
                            c_records,
                            country=c_display,
                            current_time=formatted_time
                        )
                        c_subject = f"Enterprise Pre-Check Report - {c_display}"
                        send_enterprise_email(c_html, c_subject, impersonated_user, country_recipient)
                    except Exception as country_email_err:
                        print(f"Non-fatal error sending email for country '{country_key}': {country_email_err}", file=sys.stderr)

            # 5. Since the saves succeeded, it is now safe to move the files
            print("\nCleaning up processed files...")
            for blob in successfully_processed_blobs:
                move_file_to_processed(bucket, blob)
        else:
            print("\nNo evaluations completed. No files were moved.")

    except Exception as e:
        print(f"Failed to access bucket: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    process_pending_reports()