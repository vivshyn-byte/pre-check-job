import io
import os
import re
from datetime import datetime, timezone
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from html_formatter import (
    COUNTRY_CODE_TO_NAME,
    group_records_by_country,
    sanitize_country_code,
)

# Color palettes matching the HTML pre-check report styles
COLOR_HEADER_BG = "2C3E50"  # Dark Slate
COLOR_HEADER_FG = "FFFFFF"  # White
COLOR_TITLE_FG = "2C3E50"  # Dark Charcoal
COLOR_SUBTITLE_FG = "6C757D"  # Muted Gray
COLOR_BORDER = "E1E4E8"  # Light Gray Border
COLOR_LINK = "0056B3"  # Concur / Email Link Blue
COLOR_TEXT = "2C3E50"  # Standard Text
COLOR_ROW_ERROR_BG = "F8F9FA"  # Error Row Background
COLOR_ROW_ERROR_FG = "8C959F"  # Error Row Muted Text
COLOR_ROW_ERROR_LINK = "6E7781"  # Error Row Link

STATUS_STYLES = {
    "OK": {
        "fill": PatternFill(start_color="D1E7DD", end_color="D1E7DD", fill_type="solid"),
        "font": Font(name="Calibri", size=11, bold=True, color="0F5132"),
    },
    "APPROVED": {
        "fill": PatternFill(start_color="D1E7DD", end_color="D1E7DD", fill_type="solid"),
        "font": Font(name="Calibri", size=11, bold=True, color="0F5132"),
    },
    "REVIEW": {
        "fill": PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid"),
        "font": Font(name="Calibri", size=11, bold=True, color="842029"),
    },
    "DECLINED": {
        "fill": PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid"),
        "font": Font(name="Calibri", size=11, bold=True, color="842029"),
    },
    "WARNING": {
        "fill": PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid"),
        "font": Font(name="Calibri", size=11, bold=True, color="664D03"),
    },
    "ERROR": {
        "fill": PatternFill(start_color="E2E3E5", end_color="E2E3E5", fill_type="solid"),
        "font": Font(name="Calibri", size=11, bold=True, color="41464B"),
    },
}

COLUMN_HEADERS = ["Report Details", "Country", "Owner", "Status", "Reasoning"]


def format_reasoning(reasoning, expense_purposes=None):
    """Formats reasoning text: converts delimiters/HTML breaks to newlines and enriches expense IDs."""
    if not reasoning:
        return ""

    text = str(reasoning)

    # Convert pipe delimiters and HTML <br> tags into standard newlines
    text = re.sub(r"\s*\|\s*", "\n", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    expense_purposes = expense_purposes or {}

    def replace_expense_format(match):
        expense_id = match.group(1)
        purpose = (
            expense_purposes.get(expense_id)
            or expense_purposes.get(expense_id.upper())
            or expense_purposes.get(expense_id.lower())
            or ""
        )
        purpose_str = str(purpose).strip()
        return f"Expense: ({purpose_str}) - {expense_id}"

    pattern = r"Expense:?\s*(?:\([^)]*\)\s*-\s*)?([A-Fa-f0-9]+)"
    text = re.sub(pattern, replace_expense_format, text)

    # Normalize multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def create_excel_workbook_from_array(records, country=None, title=None, current_time=None):
    """Creates an openpyxl Workbook from a list of record dicts.

    Matches the exact structure, headers, and visual styling of the HTML pre-check report.
    """
    if not current_time:
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if title:
        heading_title = title
    elif country:
        heading_title = f"Expense Reports Pre-check Summary - {country}"
    else:
        heading_title = "Expense Reports Pre-check Summary"

    wb = openpyxl.Workbook()
    ws = wb.active
    sheet_title = f"Summary - {country}" if country else "Pre-check Summary"
    # Sheet name cannot exceed 31 chars or contain invalid chars
    clean_sheet_title = re.sub(r"[\\/*?:\[\]]", "", sheet_title)[:31]
    ws.title = clean_sheet_title

    # Ensure grid lines are visible
    ws.views.sheetView[0].showGridLines = True

    # 1. Title Block (Rows 1 and 2)
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 10  # Spacer row

    cell_title = ws["A1"]
    cell_title.value = heading_title
    cell_title.font = Font(name="Calibri", size=16, bold=True, color=COLOR_TITLE_FG)
    cell_title.alignment = Alignment(vertical="center")

    cell_subtitle = ws["A2"]
    cell_subtitle.value = f"Generated on: {current_time}"
    cell_subtitle.font = Font(name="Calibri", size=10, italic=True, color=COLOR_SUBTITLE_FG)
    cell_subtitle.alignment = Alignment(vertical="center")

    # 2. Table Header Block (Row 4)
    header_row_idx = 4
    ws.row_dimensions[header_row_idx].height = 26

    header_font = Font(name="Calibri", size=11, bold=True, color=COLOR_HEADER_FG)
    header_fill = PatternFill(start_color=COLOR_HEADER_BG, end_color=COLOR_HEADER_BG, fill_type="solid")
    border_side = Side(style="thin", color=COLOR_BORDER)
    header_border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)

    header_alignments = [
        Alignment(horizontal="left", vertical="center"),    # Report Details
        Alignment(horizontal="center", vertical="center"),  # Country
        Alignment(horizontal="left", vertical="center"),    # Owner
        Alignment(horizontal="center", vertical="center"),  # Status
        Alignment(horizontal="left", vertical="center"),    # Reasoning
    ]

    for col_idx, col_name in enumerate(COLUMN_HEADERS, start=1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = header_border
        cell.alignment = header_alignments[col_idx - 1]

    # 3. Data Rows Block (Row 5+)
    start_data_row = 5
    default_font = Font(name="Calibri", size=11, color=COLOR_TEXT)
    link_font = Font(name="Calibri", size=11, color=COLOR_LINK, underline="single")
    cell_border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)

    for i, row in enumerate(records):
        current_row_idx = start_data_row + i

        status = row.get("Pre-check result", "Unknown")
        status_str = str(status).strip()
        status_key = status_str.upper()
        is_error = status_key == "ERROR"

        country_val = row.get("Country") or row.get("country", "")
        report_id = row.get("ReportID", "")
        report_name = row.get("Report name", "")
        owner_email = row.get("Owner e-mail", "")
        raw_reasoning = row.get("Result Reasoning", "")

        expense_purposes = row.get("expense_purposes") or {}
        if not expense_purposes and "expenseEntries" in row:
            expense_purposes = {
                str(entry.get("expenseId")): entry.get("businessPurpose", "")
                for entry in row.get("expenseEntries", [])
                if isinstance(entry, dict) and entry.get("expenseId")
            }

        formatted_reasoning = format_reasoning(raw_reasoning, expense_purposes)

        # Build Concur Link
        concur_link = (
            f"https://us2.concursolutions.com/nui/expense/reports/{report_id}"
            if report_id and str(report_id).upper() != "UNKNOWN"
            else None
        )

        # Base row style
        row_font = Font(name="Calibri", size=11, color=COLOR_ROW_ERROR_FG) if is_error else default_font
        row_fill = (
            PatternFill(start_color=COLOR_ROW_ERROR_BG, end_color=COLOR_ROW_ERROR_BG, fill_type="solid")
            if is_error
            else None
        )
        row_link_font = (
            Font(name="Calibri", size=11, color=COLOR_ROW_ERROR_LINK, underline="single")
            if is_error
            else link_font
        )

        # Col 1: Report Details (with hyperlink to Concur)
        cell_report = ws.cell(row=current_row_idx, column=1, value=report_name or report_id or "Report")
        cell_report.border = cell_border
        cell_report.alignment = Alignment(horizontal="left", vertical="center")
        if row_fill:
            cell_report.fill = row_fill
        if concur_link:
            cell_report.hyperlink = concur_link
            cell_report.font = row_link_font
        else:
            cell_report.font = row_font

        # Col 2: Country
        cell_country = ws.cell(row=current_row_idx, column=2, value=country_val)
        cell_country.font = row_font
        cell_country.border = cell_border
        cell_country.alignment = Alignment(horizontal="center", vertical="center")
        if row_fill:
            cell_country.fill = row_fill

        # Col 3: Owner (with mailto hyperlink)
        cell_owner = ws.cell(row=current_row_idx, column=3, value=owner_email)
        cell_owner.border = cell_border
        cell_owner.alignment = Alignment(horizontal="left", vertical="center")
        if row_fill:
            cell_owner.fill = row_fill
        if owner_email and "@" in str(owner_email):
            cell_owner.hyperlink = f"mailto:{owner_email}"
            cell_owner.font = row_link_font
        else:
            cell_owner.font = row_font

        # Col 4: Status (with color badge styling)
        cell_status = ws.cell(row=current_row_idx, column=4, value=status_str)
        cell_status.border = cell_border
        cell_status.alignment = Alignment(horizontal="center", vertical="center")
        status_style = STATUS_STYLES.get(status_key)
        if status_style:
            cell_status.fill = status_style["fill"]
            cell_status.font = status_style["font"]
        else:
            cell_status.font = row_font
            if row_fill:
                cell_status.fill = row_fill

        # Col 5: Reasoning (with line wraps)
        cell_reasoning = ws.cell(row=current_row_idx, column=5, value=formatted_reasoning)
        cell_reasoning.font = row_font
        cell_reasoning.border = cell_border
        cell_reasoning.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
        if row_fill:
            cell_reasoning.fill = row_fill

        # Set row height dynamically if reasoning has multiple lines
        lines_count = formatted_reasoning.count("\n") + 1 if formatted_reasoning else 1
        ws.row_dimensions[current_row_idx].height = max(22, lines_count * 18)

    # 4. Auto-fit column widths with bounds
    col_width_constraints = {
        1: (30, 48),  # Report Details
        2: (14, 20),  # Country
        3: (26, 42),  # Owner
        4: (14, 18),  # Status
        5: (55, 90),  # Reasoning
    }

    for col_idx in range(1, 6):
        col_letter = get_column_letter(col_idx)
        min_w, max_w = col_width_constraints.get(col_idx, (15, 50))

        # Sample values to calculate ideal width
        max_len = 0
        for cell in ws[col_letter]:
            # Don't size based on title or subtitle in rows 1 and 2
            if cell.row < header_row_idx:
                continue
            val_str = str(cell.value or "")
            if "\n" in val_str:
                val_lines = val_str.split("\n")
                line_max = max(len(l) for l in val_lines) if val_lines else 0
                max_len = max(max_len, line_max)
            else:
                max_len = max(max_len, len(val_str))

        ws.column_dimensions[col_letter].width = max(min_w, min(max_len + 4, max_w))

    return wb


def generate_excel_from_array(records, country=None, title=None, current_time=None) -> bytes:
    """Takes a list of dictionary records and returns the Excel spreadsheet (.xlsx) as bytes.

    Optional parameters:
      - country: Optional country name/code to display in the title and header.
      - title: Optional full custom title.
      - current_time: Optional pre-formatted UTC time string to synchronize with batch.
    """
    wb = create_excel_workbook_from_array(
        records, country=country, title=title, current_time=current_time
    )
    buffer = io.BytesIO()
    wb.save(buffer)
    excel_bytes = buffer.getvalue()
    buffer.close()
    return excel_bytes


def save_excel_to_gcs(bucket, excel_bytes, timestamp=None, country=None, destination_blob_name=None):
    """Saves the Excel report bytes as a new .xlsx file in the results/ directory on GCS.

    Parameters:
      - bucket: google.cloud.storage.Bucket object or string bucket name (defaults to 'reports_to_check').
      - excel_bytes: bytes of the XLSX spreadsheet.
      - timestamp: Optional timestamp string (YYYYMMDD_HHMMSS).
      - country: Optional country code or name for country-scoped reports.
      - destination_blob_name: Optional explicit blob path.
    """
    if isinstance(bucket, str) or bucket is None:
        from google.cloud import storage

        bucket_name = bucket or os.environ.get("BUCKET_NAME", "reports_to_check")
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

    if not destination_blob_name:
        if not timestamp:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if country:
            country_suffix = sanitize_country_code(country)
            destination_blob_name = f"results/batch_result_{timestamp}_{country_suffix}.xlsx"
        else:
            destination_blob_name = f"results/batch_result_{timestamp}.xlsx"

    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(
        excel_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    label = f" ({country})" if country else " (global)"
    print(f"    [+] Saved Excel report{label} to gs://{bucket.name}/{destination_blob_name}")
    return destination_blob_name


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Generate Excel pre-check result report from JSON.")
    parser.add_argument("--input", "-i", required=True, help="Path to input batch results JSON file")
    parser.add_argument("--output", "-o", help="Path to output XLSX file (default: saved alongside input or to GCS)")
    parser.add_argument("--country", "-c", help="Country name/code for single-country report")
    parser.add_argument("--save-to-gcs", action="store_true", help="Upload the generated XLSX file to GCS")
    parser.add_argument("--bucket", default=os.environ.get("BUCKET_NAME", "reports_to_check"), help="GCS bucket name")

    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as err:
        print(f"Error loading input file '{args.input}': {err}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(records, list):
        records = [records]

    excel_data = generate_excel_from_array(records, country=args.country)

    if args.output:
        with open(args.output, "wb") as f:
            f.write(excel_data)
        print(f"Saved local Excel report to: {args.output}")

    if args.save_to_gcs:
        save_excel_to_gcs(args.bucket, excel_data, country=args.country)

