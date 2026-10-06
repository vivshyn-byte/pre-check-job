import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from google.oauth2 import service_account
from googleapiclient.discovery import build

def send_enterprise_email(html_content, subject, impersonated_user, recipient):
    """Sends email via Gmail API using Domain-Wide Delegation."""
    
    # 1. Load service account credentials with a private key (required for Domain-Wide Delegation)
    scopes = ['https://www.googleapis.com/auth/gmail.send']
    key_path = os.environ.get("SERVICE_ACCOUNT_FILE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    key_json = os.environ.get("SERVICE_ACCOUNT_INFO")

    if key_json:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(key_json), scopes=scopes
        )
    elif key_path:
        credentials = service_account.Credentials.from_service_account_file(
            key_path, scopes=scopes
        )
    else:
        raise ValueError(
            "Domain-wide delegation requires a service account key. "
            "Set SERVICE_ACCOUNT_FILE, GOOGLE_APPLICATION_CREDENTIALS, or SERVICE_ACCOUNT_INFO."
        )
    
    # 2. Instruct the service account to act as the authorized Workspace user
    delegated_credentials = credentials.with_subject(impersonated_user)
    
    # 3. Build the Gmail service client
    service = build('gmail', 'v1', credentials=delegated_credentials)

    # 4. Construct the email
    msg = MIMEMultipart()
    msg['To'] = recipient
    msg['From'] = impersonated_user
    msg['Subject'] = subject
    msg.attach(MIMEText(html_content, 'html'))

    # The API requires the message to be base64url encoded
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    
    try:
        service.users().messages().send(
            userId='me', 
            body={'raw': raw_message}
        ).execute()
        print(f"    [+] Successfully sent enterprise API report to {recipient}")
    except Exception as e:
        print(f"    [-] Failed to send email via API: {e}")