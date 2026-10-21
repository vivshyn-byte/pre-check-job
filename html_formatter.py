import re
import unicodedata
from datetime import datetime, timezone

COUNTRY_CODE_TO_NAME = {
    "UA": "Ukraine",
    "US": "United States",
    "UK": "United Kingdom",
    "DE": "Germany",
    "SK": "Slovakia",
    "IN": "India",
    "CO": "Colombia",
}

COUNTRY_NAME_TO_CODE = {
    name.upper(): code for code, name in COUNTRY_CODE_TO_NAME.items()
}
COUNTRY_NAME_TO_CODE.update(
    {name.upper().replace(" ", "_"): code for code, name in COUNTRY_CODE_TO_NAME.items()}
)
COUNTRY_NAME_TO_CODE.update({code.upper(): code for code in COUNTRY_CODE_TO_NAME})


def sanitize_country_code(country):
    """Normalizes and sanitizes a country string into a safe identifier (e.g. for filenames).

    Maps known country names and codes (e.g. 'United States' or 'US') to standard country codes.
    Empty, missing, or 'UNKNOWN' values return 'UNKNOWN'.
    """
    if not country:
        return "UNKNOWN"

    country_str = str(country).strip()
    if not country_str or country_str.upper() in ["UNKNOWN", "NONE", "NULL"]:
        return "UNKNOWN"

    # Normalize unicode (decompose accented chars like e.g. Côte -> Cote)
    normalized = unicodedata.normalize("NFKD", country_str).encode("ascii", "ignore").decode("ascii").strip()
    upper_normalized = normalized.upper()
    if upper_normalized in COUNTRY_NAME_TO_CODE:
        return COUNTRY_NAME_TO_CODE[upper_normalized]

    # Replace non-alphanumeric chars with underscore
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").upper()
    return COUNTRY_NAME_TO_CODE.get(sanitized, sanitized) or "UNKNOWN"

def group_records_by_country(records):
    """Groups a list of record dicts by their sanitized country code.

    Returns a dict mapping:
        country_key -> {"display_name": str, "records": list}
    """
    groups = {}
    for record in records:
        raw_country = record.get("Country") or record.get("country")
        country_key = sanitize_country_code(raw_country)
        if country_key not in groups:
            display_name = (
                COUNTRY_CODE_TO_NAME.get(country_key)
                or (str(raw_country).strip() if raw_country and str(raw_country).strip() else country_key)
            )
            groups[country_key] = {
                "display_name": display_name,
                "records": []
            }
        groups[country_key]["records"].append(record)
    return groups

def generate_html_content_from_array(records, country=None, title=None, current_time=None):
    """Takes a list of dictionary records and returns an HTML string.

    Optional parameters:
      - country: Optional country name/code to display in the title and header.
      - title: Optional full custom title.
      - current_time: Optional pre-formatted UTC time string to synchronize with batch.
    """
    if not current_time:
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if title:
        page_title = title
        heading_title = title
    elif country:
        page_title = f"Expense Pre-check Results - {country}"
        heading_title = f"Expense Reports Pre-check Summary - {country}"
    else:
        page_title = "Expense Pre-check Results"
        heading_title = "Expense Reports Pre-check Summary"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{page_title}</title>
    <style>
        body {{ font-family: sans-serif; padding: 25px; color: #2c3e50; background-color: #f8f9fc; }}
        table {{ width: 100%; border-collapse: collapse; background-color: #ffffff; }}
        th, td {{ text-align: left; padding: 14px; border-bottom: 1px solid #e1e4e8; }}
        .status-approved {{ background-color: #d1e7dd; color: #0f5132; padding: 4px 8px; border-radius: 12px; }}
        .status-declined {{ background-color: #f8d7da; color: #842029; padding: 4px 8px; border-radius: 12px; }}
        .status-warning {{ background-color: #fff3cd; color: #664d03; padding: 4px 8px; border-radius: 12px; }}

        .status-ok {{ background-color: #d1e7dd; color: #0f5132; padding: 4px 8px; border-radius: 12px; }}
        .status-review {{ background-color: #f8d7da; color: #842029; padding: 4px 8px; border-radius: 12px; }}

        a {{ color: #0056b3; text-decoration: none; font-weight: 500; }}
        a:hover {{ text-decoration: underline; }}
        .timestamp-subtitle {{ font-size: 0.9em; color: #6c757d; margin-top: -10px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h2>{heading_title}</h2>
    <p class="timestamp-subtitle">Generated on: {current_time}</p>
    <table>
        <tr><th>Report Details</th><th>Country</th><th>Owner</th><th>Status</th><th>Reasoning</th></tr>
"""
    for row in records:
        status = row.get("Pre-check result", "Unknown")
        status_class = f"status-{status.lower()}" if status in ["OK", "Review", "Warning"] else ""
        #status_class = f"status-{status.lower()}" if status in ["Approved", "Declined", "Warning"] else ""
        # We still extract the ReportID to construct the URL, even though it's hidden
        country = row.get("Country") or row.get("country", "")
        report_id = row.get("ReportID", "")
        report_name = row.get("Report name", "")
        owner_email = row.get("Owner e-mail", "")
        reasoning = row.get("Result Reasoning", "")

        if reasoning:
            # Add line break after each reasoning entry (pipe delimiter or newline)
            reasoning = re.sub(r"\s*\|\s*", "<br>", reasoning)
            reasoning = reasoning.replace("\n", "<br>")

            if report_id:
                def replace_expense_link(match):
                    expense_id = match.group(1)
                    concur_expense_link = (
                        f"https://us2.concursolutions.com/nui/expense/reports/{report_id}/expenses/{expense_id}"
                    )
                    # Make the entire "Expense: <expense_id>" clickable
                    return f'<a href="{concur_expense_link}" target="_blank" rel="noopener noreferrer">Expense: {expense_id}</a> '

                # Matches "Expense: <expenseID>" followed by optional whitespace
                pattern = r"Expense:?\s*([A-F0-9]+)\s*"
                reasoning = re.sub(pattern, replace_expense_link, reasoning)
        
        concur_link = f"https://us2.concursolutions.com/nui/expense/reports/{report_id}" if report_id else "#"
        
        html_content += f"""
        <tr>
            <td><a href="{concur_link}" target="_blank" rel="noopener noreferrer">{report_name}</a></td>
            <td>{country}</td>
            <td><a href="mailto:{owner_email}">{owner_email}</a></td>
            <td><span class="{status_class}">{status}</span></td>
            <td>{reasoning}</td>
        </tr>"""

    html_content += """
    </table>
</body>
</html>"""
    
    return html_content