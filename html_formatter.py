from datetime import datetime

def generate_html_content_from_array(records):
    """Takes a list of dictionary records and returns an HTML string."""
    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Expense Pre-check Results</title>
    <style>
        body {{ font-family: sans-serif; padding: 25px; color: #2c3e50; background-color: #f8f9fc; }}
        table {{ width: 100%; border-collapse: collapse; background-color: #ffffff; }}
        th, td {{ text-align: left; padding: 14px; border-bottom: 1px solid #e1e4e8; }}
        .status-approved {{ background-color: #d1e7dd; color: #0f5132; padding: 4px 8px; border-radius: 12px; }}
        .status-declined {{ background-color: #f8d7da; color: #842029; padding: 4px 8px; border-radius: 12px; }}
        .status-warning {{ background-color: #fff3cd; color: #664d03; padding: 4px 8px; border-radius: 12px; }}
        a {{ color: #0056b3; text-decoration: none; font-weight: 500; }}
        a:hover {{ text-decoration: underline; }}
        .timestamp-subtitle {{ font-size: 0.9em; color: #6c757d; margin-top: -10px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h2>Expense Reports Pre-check Summary</h2>
    <p class="timestamp-subtitle">Generated on: {current_time}</p>
    <table>
        <tr><th>Report Details</th><th>Owner</th><th>Status</th><th>Reasoning</th></tr>
"""
    for row in records:
        status = row.get("Pre-check result", "Unknown")
        status_class = f"status-{status.lower()}" if status in ["Approved", "Declined", "Warning"] else ""
        
        # We still extract the ReportID to construct the URL, even though it's hidden
        report_id = row.get("ReportID", "")
        report_name = row.get("Report name", "")
        owner_email = row.get("Owner e-mail", "")
        reasoning = row.get("Result Reasoning", "")
        
        concur_link = f"https://us2.concursolutions.com/nui/expense/reports/{report_id}" if report_id else "#"
        
        html_content += f"""
        <tr>
            <td><a href="{concur_link}" target="_blank" rel="noopener noreferrer">{report_name}</a></td>
            <td><a href="mailto:{owner_email}">{owner_email}</a></td>
            <td><span class="{status_class}">{status}</span></td>
            <td>{reasoning}</td>
        </tr>"""

    html_content += """
    </table>
</body>
</html>"""
    
    return html_content