"""
Analysis Tool
=============
Pandas-based Exploratory Data Analysis with bounded output.

The EDA report is truncated to fit within the LLM context budget
so it never floods the conversation history.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from core.config import get_settings
from observability.logger import get_logger

log = get_logger(__name__)

# Maximum characters in the EDA report to prevent context saturation
_MAX_REPORT_CHARS = 4000


def run_pandas_eda(csv_path: str) -> str:
    """Perform comprehensive EDA on a CSV file.

    Parameters
    ----------
    csv_path:
        Path relative to the data/ directory (e.g., ``"sample.csv"``).

    Returns
    -------
    str
        Formatted EDA report text, truncated to ``_MAX_REPORT_CHARS``.
    """
    settings = get_settings()
    full_path = settings.data_dir / csv_path.strip().lstrip("/\\")

    if not full_path.is_file():
        return json.dumps({"error": f"File not found: {csv_path}"})

    try:
        df = pd.read_csv(str(full_path))
    except Exception as exc:
        return json.dumps({"error": f"Cannot read CSV: {exc}"})

    report: list[str] = []
    report.append(f"═══ EDA Report: {csv_path} ═══\n")
    report.append(f"📊 Shape: {df.shape[0]} rows × {df.shape[1]} columns\n")

    # Column types
    report.append("📋 Columns & Types:")
    for col in df.columns:
        report.append(f"  • {col}: {df[col].dtype}")
    report.append("")

    # Summary statistics — limit width
    report.append("📈 Summary Statistics:")
    desc = df.describe(include="all")
    # Truncate to first 15 columns to avoid massive output
    if desc.shape[1] > 15:
        desc = desc.iloc[:, :15]
        report.append(f"  (Showing first 15 of {df.shape[1]} columns)")
    report.append(desc.to_string())
    report.append("")

    # Missing values
    missing = df.isnull().sum()
    total_missing = missing.sum()
    if total_missing > 0:
        report.append("⚠️ Missing Values:")
        for col, count in missing[missing > 0].items():
            pct = round(count / len(df) * 100, 1)
            report.append(f"  • {col}: {count} ({pct}%)")
    else:
        report.append("✅ No missing values found.")
    report.append("")

    # Correlations
    numeric_df = df.select_dtypes(include=["number"])
    if not numeric_df.empty and len(numeric_df.columns) > 1:
        corr = numeric_df.corr().round(3)
        # Limit to 10×10 matrix
        if corr.shape[0] > 10:
            corr = corr.iloc[:10, :10]
            report.append("🔗 Correlation Matrix (top 10 columns):")
        else:
            report.append("🔗 Correlation Matrix:")
        report.append(corr.to_string())
    report.append("")

    # Categorical summaries
    cat_cols = df.select_dtypes(include=["object"]).columns
    if len(cat_cols) > 0:
        report.append("🏷️ Categorical Summaries:")
        for col in cat_cols[:10]:  # Limit categories
            report.append(f"\n  {col} (unique: {df[col].nunique()}):")
            for val, count in df[col].value_counts().head(5).items():
                report.append(f"    {val}: {count}")

    # Data quality
    report.append("\n📋 Data Quality:")
    dup_count = df.duplicated().sum()
    report.append(f"  • Duplicate rows: {dup_count}")
    report.append(f"  • Total nulls: {total_missing}")
    report.append(f"  • Memory usage: {df.memory_usage(deep=True).sum() / 1024:.1f} KB")

    full_report = "\n".join(report)

    # Truncate to budget
    if len(full_report) > _MAX_REPORT_CHARS:
        full_report = (
            full_report[:_MAX_REPORT_CHARS]
            + "\n\n... [Report truncated to fit context budget] ..."
        )
        log.info(
            "eda_report_truncated",
            original_len=len("\n".join(report)),
            truncated_to=_MAX_REPORT_CHARS,
        )

    return full_report
