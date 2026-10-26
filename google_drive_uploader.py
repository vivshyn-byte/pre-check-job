import io
import json
import logging
import os
import sys
from typing import Any, Dict, Optional, Union
import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

logger = logging.getLogger(__name__)

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def get_drive_credentials(
    scopes: Optional[list] = None,
    key_path: Optional[str] = None,
    key_json: Optional[str] = None,
):
    """Loads Google Cloud credentials for Google Drive API.

    Resolves credentials in the following order:
      1. Provided or environment `SERVICE_ACCOUNT_INFO` (JSON string).
      2. Provided or environment `SERVICE_ACCOUNT_FILE` or `GOOGLE_APPLICATION_CREDENTIALS` (file path).
      3. Application Default Credentials (ADC) via `google.auth.default`.
    """
    scopes = scopes or DRIVE_SCOPES
    key_json = key_json or os.environ.get("SERVICE_ACCOUNT_INFO")
    key_path = key_path or os.environ.get("SERVICE_ACCOUNT_FILE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if key_json:
        try:
            info = json.loads(key_json)
            return service_account.Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            logger.error(f"Failed to parse SERVICE_ACCOUNT_INFO JSON: {e}")
            raise

    if key_path:
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"Service account file not found: {key_path}")
        return service_account.Credentials.from_service_account_file(key_path, scopes=scopes)

    # Fallback to Application Default Credentials
    try:
        credentials, _ = google.auth.default(scopes=scopes)
        return credentials
    except Exception as e:
        raise ValueError(
            "Could not load Google Drive credentials. Set SERVICE_ACCOUNT_FILE, "
            "GOOGLE_APPLICATION_CREDENTIALS, or configure Application Default Credentials."
        ) from e


def get_drive_service(credentials=None, scopes: Optional[list] = None):
    """Builds and returns the Google Drive v3 API service resource."""
    if credentials is None:
        credentials = get_drive_credentials(scopes=scopes)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def upload_excel_to_drive(
    file_content: Union[bytes, io.BytesIO, str],
    filename: str,
    folder_id: Optional[str] = None,
    mime_type: str = XLSX_MIME_TYPE,
    service: Optional[Any] = None,
    supports_all_drives: bool = True,
) -> Dict[str, Any]:
    """Uploads Excel report content to Google Drive.

    Parameters:
      - file_content: bytes, io.BytesIO buffer, or local file path string.
      - filename: Destination name of the file in Google Drive.
      - folder_id: ID of the parent Google Drive folder or Shared Drive.
      - mime_type: MIME type of the file (defaults to openxmlformats spreadsheet).
      - service: Optional pre-authenticated Drive API service instance.
      - supports_all_drives: Whether to support Shared Drives (Team Drives).

    Returns:
      A dictionary containing:
        - 'id': Google Drive file ID
        - 'name': Name of uploaded file
        - 'web_view_link': URL to view file in browser / Google Sheets
        - 'web_content_link': Direct download URL
    """
    if not folder_id:
        folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        if not folder_id:
            raise ValueError("Google Drive folder ID must be provided or set via GOOGLE_DRIVE_FOLDER_ID.")

    if service is None:
        service = get_drive_service()

    # Prepare media upload from bytes, file-like object, or file path
    if isinstance(file_content, bytes):
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=mime_type, resumable=False)
    elif hasattr(file_content, "read"):
        media = MediaIoBaseUpload(file_content, mimetype=mime_type, resumable=False)
    elif isinstance(file_content, str):
        if not os.path.exists(file_content):
            raise FileNotFoundError(f"Local file to upload not found: {file_content}")
        media = MediaFileUpload(file_content, mimetype=mime_type, resumable=False)
    else:
        raise TypeError("file_content must be bytes, a file-like stream, or a valid path string.")

    file_metadata: Dict[str, Any] = {
        "name": filename,
        "parents": [folder_id],
    }

    create_kwargs: Dict[str, Any] = {
        "body": file_metadata,
        "media_body": media,
        "fields": "id, name, webViewLink, webContentLink",
        "supportsAllDrives": supports_all_drives,
    }

    result = service.files().create(**create_kwargs).execute()

    file_id = result.get("id")
    web_view_link = result.get("webViewLink")
    print(f"    [+] Saved Excel report to Google Drive: {filename} (ID: {file_id})")
    if web_view_link:
        print(f"    [+] Google Drive Link: {web_view_link}")

    return {
        "id": file_id,
        "name": result.get("name", filename),
        "web_view_link": web_view_link,
        "web_content_link": result.get("webContentLink"),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Upload file to Google Drive.")
    parser.add_argument("file", help="Path to local file to upload")
    parser.add_argument("--name", help="Custom name for the file in Google Drive", default=None)
    parser.add_argument("--folder-id", help="Target Google Drive folder ID", default=None)
    args = parser.parse_args()

    target_name = args.name or os.path.basename(args.file)
    try:
        res = upload_excel_to_drive(args.file, target_name, folder_id=args.folder_id)
        print("Upload successful:", res)
    except Exception as err:
        print(f"Error uploading to Google Drive: {err}", file=sys.stderr)
        sys.exit(1)
