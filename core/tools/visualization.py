"""
Visualization Tool
==================
Type-safe chart generation using matplotlib and seaborn.

* Pydantic-validated inputs — no raw LLM arguments reach matplotlib.
* Context-manager figure lifecycle — no leaked figures on error paths.
* Sandboxed output path — charts are always written to ``outputs/``.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

import matplotlib
import pandas as pd

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import seaborn as sns  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

from core.config import get_settings  # noqa: E402
from core.models import ChartType  # noqa: E402
from observability.logger import get_logger  # noqa: E402

log = get_logger(__name__)


class ChartRequest(BaseModel):
    """Validated chart generation parameters."""

    chart_type: ChartType
    csv_path: str = Field(
        ..., description="CSV file path relative to data/ directory."
    )
    x_column: str = Field(..., description="Column for the x-axis.")
    y_column: str = Field(
        default="", description="Column for the y-axis (optional for histogram/pie)."
    )
    title: str = Field(default="Chart", max_length=200)
    hue_column: str = Field(
        default="", description="Optional column for colour grouping."
    )

    @field_validator("csv_path")
    @classmethod
    def _clean_csv_path(cls, v: str) -> str:
        return v.strip().lstrip("/\\")


@contextmanager
def _safe_figure(
    figsize: tuple[float, float] = (10, 6),
) -> Generator[tuple[plt.Figure, plt.Axes], None, None]:
    """Context manager ensuring matplotlib figures are always closed."""
    fig, ax = plt.subplots(figsize=figsize)
    try:
        yield fig, ax
    finally:
        plt.close(fig)


def generate_chart(
    chart_type: str,
    csv_path: str,
    x_column: str,
    y_column: str = "",
    title: str = "Chart",
    hue_column: str = "",
) -> str:
    """Generate a chart from CSV data and save to outputs/.

    Returns
    -------
    str
        JSON with ``status``, ``file_path``, or ``error``.
    """
    settings = get_settings()

    # Validate inputs via Pydantic
    try:
        req = ChartRequest(
            chart_type=chart_type,
            csv_path=csv_path,
            x_column=x_column,
            y_column=y_column,
            title=title,
            hue_column=hue_column,
        )
    except Exception as exc:
        return json.dumps({"error": f"Invalid chart parameters: {exc}"})

    # Resolve file path within sandbox
    full_path = settings.data_dir / req.csv_path
    if not full_path.is_file():
        return json.dumps({"error": f"File not found: {req.csv_path}"})

    try:
        df = pd.read_csv(str(full_path))
    except Exception as exc:
        return json.dumps({"error": f"Cannot read CSV: {exc}"})

    available = list(df.columns)
    if req.x_column not in available:
        return json.dumps(
            {"error": f"Column '{req.x_column}' not found. Available: {available}"}
        )
    if req.y_column and req.y_column not in available:
        return json.dumps(
            {"error": f"Column '{req.y_column}' not found. Available: {available}"}
        )

    hue = req.hue_column if req.hue_column and req.hue_column in available else None

    with _safe_figure() as (fig, ax):
        try:
            _render_chart(df, req, ax, hue)
        except Exception as exc:
            return json.dumps({"error": f"Chart rendering error: {exc}"})

        ax.set_title(req.title, fontsize=14, fontweight="bold")
        fig.tight_layout()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{req.chart_type.value}_{timestamp}.png"
        save_path = settings.outputs_dir / filename
        fig.savefig(
            str(save_path),
            dpi=150,
            bbox_inches="tight",
            facecolor="#1a1a2e",
            edgecolor="none",
        )

    log.info("chart_generated", chart_type=req.chart_type.value, path=filename)

    return json.dumps(
        {
            "status": "success",
            "chart_type": req.chart_type.value,
            "file_path": f"outputs/{filename}",
            "message": f"Chart saved to outputs/{filename}",
        }
    )


def _render_chart(
    df: pd.DataFrame,
    req: ChartRequest,
    ax: plt.Axes,
    hue: str | None,
) -> None:
    """Dispatch chart rendering to the correct seaborn/matplotlib call."""
    ct = req.chart_type

    if ct == ChartType.BAR:
        if req.y_column:
            sns.barplot(data=df, x=req.x_column, y=req.y_column, hue=hue, ax=ax)
        else:
            df[req.x_column].value_counts().plot(kind="bar", ax=ax, color="#7b68ee")

    elif ct == ChartType.SCATTER:
        sns.scatterplot(data=df, x=req.x_column, y=req.y_column, hue=hue, ax=ax, s=80)

    elif ct == ChartType.LINE:
        sns.lineplot(data=df, x=req.x_column, y=req.y_column, hue=hue, ax=ax, marker="o")

    elif ct == ChartType.HISTOGRAM:
        sns.histplot(data=df, x=req.x_column, hue=hue, ax=ax, kde=True, color="#00d4ff")

    elif ct == ChartType.BOX:
        if req.y_column:
            sns.boxplot(data=df, x=req.x_column, y=req.y_column, hue=hue, ax=ax)
        else:
            sns.boxplot(data=df, y=req.x_column, ax=ax)

    elif ct == ChartType.HEATMAP:
        numeric_df = df.select_dtypes(include=["number"])
        if numeric_df.empty:
            raise ValueError("No numeric columns available for heatmap.")
        sns.heatmap(numeric_df.corr(), annot=True, cmap="coolwarm", ax=ax, fmt=".2f")

    elif ct == ChartType.PIE:
        counts = df[req.x_column].value_counts()
        ax.pie(counts.values, labels=counts.index, autopct="%1.1f%%", startangle=90)
        ax.set_aspect("equal")
