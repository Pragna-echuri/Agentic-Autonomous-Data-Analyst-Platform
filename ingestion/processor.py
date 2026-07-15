"""
Multi-Format Ingestion Processor
=================================
Handles file ingestion for:

* **Tabular**: CSV, XLSX, XLS, JSON, JSONL, Parquet, Feather
* **Document**: PDF, XML
* **Image**: PNG, JPG, JPEG (OCR text extraction)

All processing is **local** — no LLM calls.  Only metadata (schema,
statistics, previews) reaches the LLM context.

Dependencies are imported lazily with graceful degradation: missing
optional packages (openpyxl, pdfplumber, pyarrow) produce clear
error messages rather than import crashes.
"""

from __future__ import annotations

import csv
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import get_settings
from core.models import ColumnProfile, FileCategory, IngestionResult
from observability.logger import get_logger

log = get_logger(__name__)

# Maximum rows loaded for profiling (memory guard)
_MAX_PROFILE_ROWS = 10_000
_MAX_PREVIEW_ROWS = 10


# ── Format Registry ─────────────────────────────────────────────────

_TABULAR_EXTENSIONS = frozenset(
    {".csv", ".xlsx", ".xls", ".json", ".jsonl", ".parquet", ".feather"}
)
_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".xml"})
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})


def categorise_file(path: Path) -> FileCategory:
    ext = path.suffix.lower()
    if ext in _TABULAR_EXTENSIONS:
        return FileCategory.TABULAR
    if ext in _DOCUMENT_EXTENSIONS:
        return FileCategory.DOCUMENT
    if ext in _IMAGE_EXTENSIONS:
        return FileCategory.IMAGE
    return FileCategory.UNKNOWN


# ── Public API ───────────────────────────────────────────────────────

def ingest_file(filepath: str | Path) -> IngestionResult:
    """Ingest a file and produce metadata + profiling.

    Parameters
    ----------
    filepath:
        Absolute or data-dir-relative path to the file.

    Returns
    -------
    IngestionResult
        Schema, statistics, preview rows, quality warnings (no raw data).
    """
    settings = get_settings()
    path = Path(filepath)
    if not path.is_absolute():
        path = settings.data_dir / path

    if not path.is_file():
        return IngestionResult(
            filename=path.name,
            quality_warnings=[f"File not found: {filepath}"],
        )

    start = time.perf_counter()
    category = categorise_file(path)
    size = path.stat().st_size

    try:
        if category == FileCategory.TABULAR:
            result = _ingest_tabular(path)
        elif category == FileCategory.DOCUMENT:
            result = _ingest_document(path)
        elif category == FileCategory.IMAGE:
            result = _ingest_image(path)
        else:
            result = IngestionResult(
                filename=path.name,
                file_category=FileCategory.UNKNOWN,
                file_size_bytes=size,
                quality_warnings=[
                    f"Unsupported file type: {path.suffix}"
                ],
            )
    except Exception as exc:
        log.error("ingestion_error", file=path.name, error=str(exc))
        result = IngestionResult(
            filename=path.name,
            file_category=category,
            file_size_bytes=size,
            quality_warnings=[f"Processing error: {exc}"],
        )

    result.file_size_bytes = size
    result.processing_time_ms = round(
        (time.perf_counter() - start) * 1000, 2
    )

    log.info(
        "file_ingested",
        file=path.name,
        category=category.value,
        rows=result.row_count,
        columns=result.column_count,
        time_ms=result.processing_time_ms,
    )

    return result


# ── Tabular Processing ───────────────────────────────────────────────

def _ingest_tabular(path: Path) -> IngestionResult:
    """Read a tabular file into a DataFrame and profile it."""
    ext = path.suffix.lower()
    df: pd.DataFrame

    if ext == ".csv":
        df = pd.read_csv(str(path), nrows=_MAX_PROFILE_ROWS)
    elif ext in (".xlsx", ".xls"):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            return IngestionResult(
                filename=path.name,
                file_category=FileCategory.TABULAR,
                quality_warnings=[
                    "Install 'openpyxl' to process Excel files: "
                    "pip install openpyxl"
                ],
            )
        df = pd.read_excel(str(path), nrows=_MAX_PROFILE_ROWS)
    elif ext == ".json":
        df = pd.read_json(str(path))
        if len(df) > _MAX_PROFILE_ROWS:
            df = df.head(_MAX_PROFILE_ROWS)
    elif ext == ".jsonl":
        df = pd.read_json(str(path), lines=True, nrows=_MAX_PROFILE_ROWS)
    elif ext == ".parquet":
        try:
            df = pd.read_parquet(str(path))
        except ImportError:
            return IngestionResult(
                filename=path.name,
                file_category=FileCategory.TABULAR,
                quality_warnings=[
                    "Install 'pyarrow' to process Parquet files: "
                    "pip install pyarrow"
                ],
            )
        if len(df) > _MAX_PROFILE_ROWS:
            df = df.head(_MAX_PROFILE_ROWS)
    elif ext == ".feather":
        try:
            df = pd.read_feather(str(path))
        except ImportError:
            return IngestionResult(
                filename=path.name,
                file_category=FileCategory.TABULAR,
                quality_warnings=[
                    "Install 'pyarrow' to process Feather files: "
                    "pip install pyarrow"
                ],
            )
        if len(df) > _MAX_PROFILE_ROWS:
            df = df.head(_MAX_PROFILE_ROWS)
    else:
        return IngestionResult(
            filename=path.name,
            file_category=FileCategory.TABULAR,
            quality_warnings=[f"Unsupported tabular format: {ext}"],
        )

    return _profile_dataframe(df, path.name)


def _profile_dataframe(df: pd.DataFrame, filename: str) -> IngestionResult:
    """Generate column profiles, previews, and quality warnings."""
    columns: list[ColumnProfile] = []
    warnings: list[str] = []

    for col in df.columns:
        series = df[col]
        null_count = int(series.isnull().sum())
        null_pct = round(null_count / len(df) * 100, 1) if len(df) > 0 else 0.0
        unique_count = int(series.nunique())
        samples = [str(v) for v in series.dropna().head(3).tolist()]

        profile = ColumnProfile(
            name=str(col),
            dtype=str(series.dtype),
            null_count=null_count,
            null_percentage=null_pct,
            unique_count=unique_count,
            sample_values=samples,
        )

        if pd.api.types.is_numeric_dtype(series):
            desc = series.describe()
            profile = profile.model_copy(
                update={
                    "min_val": float(desc.get("min", 0)),
                    "max_val": float(desc.get("max", 0)),
                    "mean_val": round(float(desc.get("mean", 0)), 4),
                    "median_val": round(float(series.median()), 4),
                    "std_val": round(float(desc.get("std", 0)), 4),
                }
            )
        elif pd.api.types.is_object_dtype(series):
            top = series.value_counts().head(5).to_dict()
            profile = profile.model_copy(
                update={"top_values": {str(k): int(v) for k, v in top.items()}}
            )

        if null_pct > 50:
            warnings.append(f"Column '{col}' has {null_pct}% missing values.")

        columns.append(profile)

    # Quality checks
    dup_count = int(df.duplicated().sum())
    if dup_count > 0:
        warnings.append(f"{dup_count} duplicate rows detected.")

    preview = df.head(_MAX_PREVIEW_ROWS).to_dict(orient="records")
    # Ensure all values are JSON-serialisable
    clean_preview: list[dict[str, Any]] = []
    for row in preview:
        clean_preview.append(
            {k: _to_serialisable(v) for k, v in row.items()}
        )

    return IngestionResult(
        filename=filename,
        file_category=FileCategory.TABULAR,
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        preview_rows=clean_preview,
        quality_warnings=warnings,
    )


def _to_serialisable(val: Any) -> Any:
    """Convert numpy/pandas types to JSON-safe Python primitives."""
    if pd.isna(val):
        return None
    if hasattr(val, "item"):
        return val.item()
    return val


# ── Document Processing ──────────────────────────────────────────────

def _ingest_document(path: Path) -> IngestionResult:
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _ingest_pdf(path)
    if ext == ".xml":
        return _ingest_xml(path)

    return IngestionResult(
        filename=path.name,
        file_category=FileCategory.DOCUMENT,
        quality_warnings=[f"Unsupported document format: {ext}"],
    )


def _ingest_pdf(path: Path) -> IngestionResult:
    try:
        import pdfplumber
    except ImportError:
        return IngestionResult(
            filename=path.name,
            file_category=FileCategory.DOCUMENT,
            quality_warnings=[
                "Install 'pdfplumber' for PDF processing: "
                "pip install pdfplumber"
            ],
        )

    text_parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages[:20]:  # Limit to 20 pages
            page_text = page.extract_text() or ""
            text_parts.append(page_text)

    full_text = "\n\n".join(text_parts)
    # Truncate for context
    if len(full_text) > 8000:
        full_text = full_text[:8000] + "\n\n... [Truncated]"

    return IngestionResult(
        filename=path.name,
        file_category=FileCategory.DOCUMENT,
        text_content=full_text,
        row_count=len(text_parts),
    )


def _ingest_xml(path: Path) -> IngestionResult:
    try:
        tree = ET.parse(str(path))  # noqa: S314
        root = tree.getroot()
        text = ET.tostring(root, encoding="unicode", method="text")[:8000]
        return IngestionResult(
            filename=path.name,
            file_category=FileCategory.DOCUMENT,
            text_content=text,
        )
    except Exception as exc:
        return IngestionResult(
            filename=path.name,
            file_category=FileCategory.DOCUMENT,
            quality_warnings=[f"XML parsing error: {exc}"],
        )


# ── Image Processing ─────────────────────────────────────────────────

def _ingest_image(path: Path) -> IngestionResult:
    """Attempt OCR on images with graceful degradation."""
    # Try pytesseract first, then easyocr
    text = _try_tesseract(path) or _try_easyocr(path)

    if text is None:
        return IngestionResult(
            filename=path.name,
            file_category=FileCategory.IMAGE,
            quality_warnings=[
                "No OCR library available. Install 'pytesseract' "
                "(+ Tesseract binary) or 'easyocr' for image text extraction."
            ],
        )

    return IngestionResult(
        filename=path.name,
        file_category=FileCategory.IMAGE,
        text_content=text[:4000],
    )


def _try_tesseract(path: Path) -> str | None:
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(str(path))
        return pytesseract.image_to_string(img)
    except ImportError:
        return None
    except Exception:
        return None


def _try_easyocr(path: Path) -> str | None:
    try:
        import easyocr

        reader = easyocr.Reader(["en"], gpu=False)
        results = reader.readtext(str(path))
        return "\n".join(r[1] for r in results)
    except ImportError:
        return None
    except Exception:
        return None
