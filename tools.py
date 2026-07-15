"""
Legacy Tools Bridge
===================
Non-MCP tool functions that handle visualization, EDA, and report
export. These are called by the orchestrator agent when the LLM
requests visualization or EDA operations.

Functions here cover capabilities that don't have dedicated MCP servers:
    - Data visualization (matplotlib, plotly, seaborn)
    - Pandas-based EDA
    - Report export (Markdown, HTML)
"""

import os
import json
import traceback
from pathlib import Path
from datetime import datetime

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server use
import matplotlib.pyplot as plt
import seaborn as sns

# ─── Configuration ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
# Tool Registry (for LLM function-calling)
# ═══════════════════════════════════════════════════════════════════════

LEGACY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": (
                "Generate a chart from CSV data and save it as a PNG image. "
                "Supported types: bar, scatter, line, histogram, box, heatmap, pie."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "scatter", "line", "histogram", "box", "heatmap", "pie"],
                        "description": "The type of chart to create.",
                    },
                    "csv_path": {
                        "type": "string",
                        "description": "Path to the CSV file (relative to data/ directory, e.g., 'sample.csv').",
                    },
                    "x_column": {
                        "type": "string",
                        "description": "Column name for the x-axis.",
                    },
                    "y_column": {
                        "type": "string",
                        "description": "Column name for the y-axis (optional for histogram/pie).",
                        "default": "",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title for the chart.",
                        "default": "Chart",
                    },
                    "hue_column": {
                        "type": "string",
                        "description": "Optional column for color grouping.",
                        "default": "",
                    },
                },
                "required": ["chart_type", "csv_path", "x_column"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_pandas_eda",
            "description": (
                "Perform comprehensive Exploratory Data Analysis on a CSV file. "
                "Returns shape, dtypes, summary statistics, missing values, "
                "correlations, and categorical column summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "csv_path": {
                        "type": "string",
                        "description": "Path to the CSV file (relative to data/ directory).",
                    },
                },
                "required": ["csv_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_report",
            "description": "Export analysis content as a Markdown or HTML report file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The report content to export.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Name for the output file (without extension).",
                        "default": "report",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "html"],
                        "description": "Output format.",
                        "default": "markdown",
                    },
                },
                "required": ["content"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════
# Tool Implementations
# ═══════════════════════════════════════════════════════════════════════

def generate_chart(
    chart_type: str,
    csv_path: str,
    x_column: str,
    y_column: str = "",
    title: str = "Chart",
    hue_column: str = "",
) -> str:
    """Generate a chart from CSV data and save it to the outputs directory."""
    try:
        full_path = DATA_DIR / csv_path if not Path(csv_path).is_absolute() else Path(csv_path)
        if not full_path.exists():
            return json.dumps({"error": f"File not found: {csv_path}"})

        df = pd.read_csv(str(full_path))

        available_cols = list(df.columns)
        if x_column not in available_cols:
            return json.dumps({"error": f"Column '{x_column}' not found. Available: {available_cols}"})
        if y_column and y_column not in available_cols:
            return json.dumps({"error": f"Column '{y_column}' not found. Available: {available_cols}"})

        fig, ax = plt.subplots(figsize=(10, 6))
        chart_type = chart_type.lower().strip()
        hue = hue_column if hue_column and hue_column in available_cols else None

        if chart_type == "bar":
            if y_column:
                sns.barplot(data=df, x=x_column, y=y_column, hue=hue, ax=ax)
            else:
                df[x_column].value_counts().plot(kind="bar", ax=ax, color="#7b68ee")
        elif chart_type == "scatter":
            sns.scatterplot(data=df, x=x_column, y=y_column, hue=hue, ax=ax, s=80)
        elif chart_type == "line":
            sns.lineplot(data=df, x=x_column, y=y_column, hue=hue, ax=ax, marker="o")
        elif chart_type == "histogram":
            sns.histplot(data=df, x=x_column, hue=hue, ax=ax, kde=True, color="#00d4ff")
        elif chart_type == "box":
            if y_column:
                sns.boxplot(data=df, x=x_column, y=y_column, hue=hue, ax=ax)
            else:
                sns.boxplot(data=df, y=x_column, ax=ax)
        elif chart_type == "heatmap":
            numeric_df = df.select_dtypes(include=["number"])
            if numeric_df.empty:
                return json.dumps({"error": "No numeric columns for heatmap."})
            sns.heatmap(numeric_df.corr(), annot=True, cmap="coolwarm", ax=ax, fmt=".2f")
        elif chart_type == "pie":
            counts = df[x_column].value_counts()
            ax.pie(counts.values, labels=counts.index, autopct="%1.1f%%", startangle=90)
            ax.set_aspect("equal")
        else:
            plt.close(fig)
            return json.dumps({"error": f"Unknown chart type '{chart_type}'."})

        ax.set_title(title, fontsize=14, fontweight="bold")
        plt.tight_layout()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{chart_type}_{timestamp}.png"
        save_path = OUTPUTS_DIR / filename
        fig.savefig(str(save_path), dpi=150, bbox_inches="tight",
                    facecolor="#1a1a2e", edgecolor="none")
        plt.close(fig)

        return json.dumps({
            "status": "success",
            "chart_type": chart_type,
            "file_path": f"outputs/{filename}",
            "message": f"Chart saved to outputs/{filename}"
        })

    except Exception as e:
        plt.close("all")
        return json.dumps({"error": f"Error generating chart: {str(e)}"})


def run_pandas_eda(csv_path: str) -> str:
    """Perform comprehensive EDA on a CSV file."""
    try:
        full_path = DATA_DIR / csv_path if not Path(csv_path).is_absolute() else Path(csv_path)
        df = pd.read_csv(str(full_path))

        report = []
        report.append(f"═══ EDA Report: {csv_path} ═══\n")
        report.append(f"📊 Shape: {df.shape[0]} rows × {df.shape[1]} columns\n")

        report.append("📋 Columns & Types:")
        for col in df.columns:
            report.append(f"  • {col}: {df[col].dtype}")
        report.append("")

        report.append("📈 Summary Statistics:")
        report.append(df.describe(include="all").to_string())
        report.append("")

        missing = df.isnull().sum()
        if missing.sum() > 0:
            report.append("⚠️ Missing Values:")
            for col, count in missing[missing > 0].items():
                pct = round(count / len(df) * 100, 1)
                report.append(f"  • {col}: {count} ({pct}%)")
        else:
            report.append("✅ No missing values found.")
        report.append("")

        numeric_df = df.select_dtypes(include=["number"])
        if not numeric_df.empty and len(numeric_df.columns) > 1:
            report.append("🔗 Correlation Matrix:")
            report.append(numeric_df.corr().round(3).to_string())
        report.append("")

        cat_cols = df.select_dtypes(include=["object"]).columns
        if len(cat_cols) > 0:
            report.append("🏷️ Categorical Summaries:")
            for col in cat_cols:
                report.append(f"\n  {col} (unique: {df[col].nunique()}):")
                for val, count in df[col].value_counts().head(5).items():
                    report.append(f"    {val}: {count}")

        return "\n".join(report)

    except Exception as e:
        return json.dumps({"error": f"EDA error: {str(e)}"})


def export_report(
    content: str,
    filename: str = "report",
    format: str = "markdown",
) -> str:
    """Export analysis content as a report file."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if format.lower() == "html":
            ext = "html"
            output = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{filename}</title>
<style>
body {{ font-family: 'Inter', sans-serif; max-width: 900px; margin: 40px auto;
       padding: 20px; background: #1a1a2e; color: #e0e0e0; }}
h1,h2,h3 {{ color: #00d4ff; }}
pre {{ background: #16213e; padding: 15px; border-radius: 8px; overflow-x: auto; }}
</style></head><body>
<h1>📊 Data Analysis Report</h1>
<pre>{content}</pre>
<p><em>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></p>
</body></html>"""
        else:
            ext = "md"
            output = f"# 📊 Data Analysis Report\n\n{content}\n\n---\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"

        save_path = OUTPUTS_DIR / f"{filename}_{timestamp}.{ext}"
        save_path.write_text(output, encoding="utf-8")

        return json.dumps({
            "status": "success",
            "file_path": f"outputs/{save_path.name}",
            "message": f"Report saved to outputs/{save_path.name}"
        })

    except Exception as e:
        return json.dumps({"error": f"Export error: {str(e)}"})


# ─── Tool Dispatcher ────────────────────────────────────────────────────────

def execute_legacy_tool(tool_name: str, arguments: dict) -> str:
    """Execute a legacy tool by name with the given arguments."""
    tools_map = {
        "generate_chart": generate_chart,
        "run_pandas_eda": run_pandas_eda,
        "export_report": export_report,
    }

    func = tools_map.get(tool_name)
    if not func:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    return func(**arguments)
