"""
Reporting Tool
==============
Export analysis content as Markdown or HTML reports to ``outputs/``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from core.config import get_settings
from core.models import ReportFormat
from observability.logger import get_logger

log = get_logger(__name__)


def export_report(
    content: str,
    filename: str = "report",
    format: str = "markdown",
) -> str:
    """Export analysis content as a report file.

    Parameters
    ----------
    content:
        The report body text.
    filename:
        Base filename (without extension).
    format:
        ``"markdown"`` or ``"html"``.

    Returns
    -------
    str
        JSON with ``status`` and ``file_path``, or ``error``.
    """
    settings = get_settings()

    try:
        fmt = ReportFormat(format.lower())
    except ValueError:
        return json.dumps(
            {"error": f"Unsupported format: '{format}'. Use 'markdown' or 'html'."}
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if fmt == ReportFormat.HTML:
        ext = "html"
        output = _build_html_report(content, filename, timestamp)
    else:
        ext = "md"
        output = _build_markdown_report(content, timestamp)

    save_path = settings.outputs_dir / f"{filename}_{timestamp}.{ext}"
    save_path.write_text(output, encoding="utf-8")

    log.info("report_exported", format=fmt.value, path=save_path.name)

    return json.dumps(
        {
            "status": "success",
            "file_path": f"outputs/{save_path.name}",
            "message": f"Report saved to outputs/{save_path.name}",
        }
    )


def _build_html_report(content: str, title: str, timestamp: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{
    font-family: 'Inter', 'Segoe UI', sans-serif;
    max-width: 900px;
    margin: 40px auto;
    padding: 20px;
    background: #1a1a2e;
    color: #e0e0e0;
    line-height: 1.6;
}}
h1, h2, h3 {{ color: #00d4ff; }}
pre {{
    background: #16213e;
    padding: 15px;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 0.9rem;
}}
</style>
</head>
<body>
<h1>📊 Data Analysis Report</h1>
<pre>{content}</pre>
<p><em>Generated: {timestamp}</em></p>
</body>
</html>"""


def _build_markdown_report(content: str, timestamp: str) -> str:
    return (
        f"# 📊 Data Analysis Report\n\n"
        f"{content}\n\n"
        f"---\n"
        f"*Generated: {timestamp}*\n"
    )
