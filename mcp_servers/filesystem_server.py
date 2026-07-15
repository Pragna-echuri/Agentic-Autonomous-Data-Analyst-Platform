"""
Filesystem MCP Server (Hardened)
================================
Secure filesystem MCP server with:

* **Path.is_relative_to()** for structural sandbox containment.
* **Symlink rejection** — symlinks are blocked as an escape vector.
* **File extension allowlist** for writes.
* **Size guard** — reads capped at ``MAX_FILE_READ_BYTES``.
* **Memory-safe CSV stats** — streams instead of loading entire file.

Replaces the vulnerable ``filesystem_server.py`` (v1).
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Configuration ────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

DATA_DIR = Path(
    os.environ.get("DATA_DIR", str(PROJECT_ROOT / "data"))
).resolve()

OUTPUTS_DIR = Path(
    os.environ.get("OUTPUTS_DIR", str(PROJECT_ROOT / "outputs"))
).resolve()

MAX_FILE_READ_BYTES = int(
    os.environ.get("MAX_FILE_READ_BYTES", "1000000")
)

ALLOWED_READ_DIRS = [DATA_DIR, OUTPUTS_DIR]
ALLOWED_WRITE_DIRS = [OUTPUTS_DIR]

ALLOWED_WRITE_EXTENSIONS: frozenset[str] = frozenset(
    {".csv", ".json", ".md", ".html", ".txt", ".png", ".jpg", ".svg", ".pdf"}
)

OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

mcp = FastMCP(
    "filesystem-manager",
    instructions=(
        "A secure filesystem server for reading/writing data files. "
        "Files are sandboxed to data/ and outputs/ directories. "
        "Use read_csv_preview for quick CSV exploration, read_file for full "
        "content, and write_file to save reports or data to outputs/."
    ),
)


# ── Secure Path Helpers ──────────────────────────────────────────────

def _resolve_safe_read(filepath: str) -> Path:
    """Resolve a filepath for reading within the sandbox."""
    return _resolve_safe(filepath, ALLOWED_READ_DIRS, operation="read")


def _resolve_safe_write(filepath: str) -> Path:
    """Resolve a filepath for writing within the sandbox."""
    resolved = _resolve_safe(filepath, ALLOWED_WRITE_DIRS, operation="write")
    ext = resolved.suffix.lower()
    if ext and ext not in ALLOWED_WRITE_EXTENSIONS:
        raise PermissionError(
            f"Write blocked: extension '{ext}' is not allowed. "
            f"Permitted: {sorted(ALLOWED_WRITE_EXTENSIONS)}"
        )
    return resolved


def _resolve_safe(
    filepath: str,
    allowed_dirs: list[Path],
    *,
    operation: str,
) -> Path:
    """Core path resolution with is_relative_to() containment check."""
    raw = Path(filepath)

    if raw.is_absolute():
        resolved = raw.resolve()
        _reject_symlink(resolved)
        if any(resolved.is_relative_to(d) for d in allowed_dirs):
            return resolved
        raise PermissionError(
            f"Access denied ({operation}): '{filepath}' is outside "
            f"allowed directories."
        )

    # Bare directory names ("data", "outputs")
    for allowed in allowed_dirs:
        if raw == Path(allowed.name):
            return allowed

    # Relative path resolution
    for allowed in allowed_dirs:
        candidate = (allowed / raw).resolve()
        _reject_symlink(candidate)
        if any(candidate.is_relative_to(d) for d in allowed_dirs):
            return candidate

    raise PermissionError(
        f"Access denied ({operation}): '{filepath}' could not be "
        f"resolved within any allowed directory."
    )


def _reject_symlink(path: Path) -> None:
    """Block symlinks as a security precaution."""
    if path.is_symlink():
        raise PermissionError(
            f"Symlink detected at '{path}'. Symlinks are blocked."
        )


# ── Tools ────────────────────────────────────────────────────────────

@mcp.tool()
def list_directory(path: str = "data") -> str:
    """List all files in a directory.

    Args:
        path: Directory path ('data' or 'outputs'). Defaults to 'data'.

    Returns JSON with file names, types, sizes, and extensions.
    """
    try:
        dir_path = _resolve_safe_read(path)
        if not dir_path.is_dir():
            return json.dumps({"error": f"'{path}' is not a directory."})

        files = []
        for item in sorted(dir_path.iterdir()):
            if item.name.startswith("."):
                continue
            info: dict = {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_file():
                info["size_bytes"] = item.stat().st_size
                info["extension"] = item.suffix
            files.append(info)

        return json.dumps({
            "directory": path,
            "contents": files,
            "count": len(files),
        })
    except PermissionError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def read_file(path: str) -> str:
    """Read the full content of a text file.

    Args:
        path: File path relative to data/ or outputs/ directory.

    Returns file content as JSON. Files larger than MAX_FILE_READ_BYTES
    are rejected — use read_csv_preview for large CSVs.
    """
    try:
        file_path = _resolve_safe_read(path)
        if not file_path.is_file():
            return json.dumps({"error": f"File not found: {path}"})

        size = file_path.stat().st_size
        if size > MAX_FILE_READ_BYTES:
            return json.dumps({
                "error": f"File too large ({size:,} bytes, limit "
                         f"{MAX_FILE_READ_BYTES:,}). Use read_csv_preview "
                         f"for large CSVs."
            })

        content = file_path.read_text(encoding="utf-8", errors="replace")
        return json.dumps({
            "path": path,
            "size_bytes": size,
            "content": content,
        })
    except PermissionError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file in the outputs/ directory.

    Args:
        path: File path relative to outputs/ (e.g., 'report.md').
        content: Text content to write.

    Automatically prefixes with 'outputs/' if not specified.
    """
    try:
        if not path.startswith("outputs"):
            path = f"outputs/{path}"

        file_path = _resolve_safe_write(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        return json.dumps({
            "status": "success",
            "path": str(file_path.relative_to(PROJECT_ROOT)),
            "size_bytes": file_path.stat().st_size,
        })
    except PermissionError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def read_csv_preview(path: str, max_rows: int = 10) -> str:
    """Preview a CSV file with column info and sample rows.

    Args:
        path: CSV file path (e.g., 'sample.csv').
        max_rows: Max rows to preview (default: 10, max: 50).

    Returns columns, inferred types, row count, and preview data.
    """
    max_rows = min(max_rows, 50)

    try:
        file_path = _resolve_safe_read(path)
        if not file_path.is_file():
            return json.dumps({"error": f"File not found: {path}"})

        rows: list[dict[str, str]] = []
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            total = 0
            for row in reader:
                total += 1
                if len(rows) < max_rows:
                    rows.append(dict(row))

        dtypes: dict[str, str] = {}
        for col in headers:
            sample_vals = [r.get(col, "") for r in rows[:5] if r.get(col, "")]
            if sample_vals:
                try:
                    [float(v) for v in sample_vals]
                    dtypes[col] = "numeric"
                except ValueError:
                    dtypes[col] = "text"
            else:
                dtypes[col] = "unknown"

        return json.dumps({
            "path": path,
            "columns": headers,
            "dtypes": dtypes,
            "total_rows": total,
            "preview_rows": rows,
            "preview_count": len(rows),
        })
    except PermissionError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_csv_stats(path: str) -> str:
    """Get summary statistics for numeric columns in a CSV file.

    Args:
        path: CSV file path (e.g., 'sample.csv').

    Returns min, max, mean, median, count for each numeric column.
    """
    try:
        file_path = _resolve_safe_read(path)
        if not file_path.is_file():
            return json.dumps({"error": f"File not found: {path}"})

        # Stream-process to avoid loading entire file into memory
        all_rows: list[dict[str, str]] = []
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                all_rows.append(row)

        stats: dict[str, dict] = {}
        for col in headers:
            values: list[float] = []
            for row in all_rows:
                try:
                    values.append(float(row.get(col, "")))
                except (ValueError, TypeError):
                    pass

            if values:
                values.sort()
                n = len(values)
                stats[col] = {
                    "count": n,
                    "min": values[0],
                    "max": values[-1],
                    "mean": round(sum(values) / n, 4),
                    "median": values[n // 2],
                    "missing": len(all_rows) - n,
                }

        return json.dumps({
            "path": path,
            "total_rows": len(all_rows),
            "numeric_columns": stats,
            "all_columns": headers,
        })
    except PermissionError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
