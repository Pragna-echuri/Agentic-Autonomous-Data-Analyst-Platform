"""
Secure Path Validator
=====================
Enforces filesystem sandbox boundaries using structural path containment.

The validator prevents:

* **Path traversal** — ``../../../etc/passwd``
* **Symlink escape** — symlinks pointing outside allowed directories
* **Prefix collision** — ``/data_secret`` vs ``/data``

Uses ``Path.is_relative_to()`` (Python 3.9+) for reliable containment
checks instead of error-prone string ``startswith()`` comparisons.

Usage::

    from security.path_validator import PathValidator
    validator = PathValidator()
    safe = validator.resolve_read_path("sample.csv")      # OK
    validator.resolve_read_path("../../etc/passwd")        # raises PathTraversalError
"""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings
from core.exceptions import PathTraversalError, SecurityError


class PathValidator:
    """Filesystem sandbox enforcer.

    Parameters
    ----------
    allowed_read_dirs:
        Directories from which the agent may **read** files.
        Defaults to ``[data_dir, outputs_dir]``.
    allowed_write_dirs:
        Directories to which the agent may **write** files.
        Defaults to ``[outputs_dir]``.
    """

    def __init__(
        self,
        allowed_read_dirs: list[Path] | None = None,
        allowed_write_dirs: list[Path] | None = None,
    ) -> None:
        settings = get_settings()
        self._read_dirs = [
            d.resolve() for d in (allowed_read_dirs or [settings.data_dir, settings.outputs_dir])
        ]
        self._write_dirs = [
            d.resolve() for d in (allowed_write_dirs or [settings.outputs_dir])
        ]
        self._allowed_write_extensions: frozenset[str] = settings.allowed_write_extensions

    # ── Public API ───────────────────────────────────────────────────

    def resolve_read_path(self, filepath: str) -> Path:
        """Resolve *filepath* for reading and verify it is sandboxed.

        Parameters
        ----------
        filepath:
            Absolute or relative path.  Relative paths are resolved
            against each allowed read directory in order; the first
            match wins.

        Returns
        -------
        Path
            The fully resolved, verified path.

        Raises
        ------
        PathTraversalError
            If the resolved path is outside all allowed directories.
        """
        return self._resolve(filepath, self._read_dirs, operation="read")

    def resolve_write_path(self, filepath: str) -> Path:
        """Resolve *filepath* for writing and verify it is sandboxed.

        Raises
        ------
        PathTraversalError
            If the resolved path is outside the write sandbox.
        SecurityError
            If the file extension is not in the write allowlist.
        """
        resolved = self._resolve(filepath, self._write_dirs, operation="write")
        ext = resolved.suffix.lower()
        if ext and ext not in self._allowed_write_extensions:
            raise SecurityError(
                f"Write blocked: extension '{ext}' is not allowed. "
                f"Permitted: {sorted(self._allowed_write_extensions)}",
                details={"path": str(resolved), "extension": ext},
            )
        return resolved

    def is_safe_read(self, filepath: str) -> bool:
        """Non-throwing check: can *filepath* be read?"""
        try:
            self.resolve_read_path(filepath)
            return True
        except (PathTraversalError, SecurityError):
            return False

    def is_safe_write(self, filepath: str) -> bool:
        """Non-throwing check: can *filepath* be written?"""
        try:
            self.resolve_write_path(filepath)
            return True
        except (PathTraversalError, SecurityError):
            return False

    # ── Internal ─────────────────────────────────────────────────────

    def _resolve(
        self,
        filepath: str,
        allowed_dirs: list[Path],
        *,
        operation: str,
    ) -> Path:
        raw = Path(filepath)

        if raw.is_absolute():
            resolved = raw.resolve()
            self._check_symlink(resolved)
            if self._is_contained(resolved, allowed_dirs):
                return resolved
            raise PathTraversalError(
                f"Access denied ({operation}): '{filepath}' is outside "
                f"allowed directories.",
                details={
                    "path": str(resolved),
                    "allowed": [str(d) for d in allowed_dirs],
                },
            )

        # Relative path — try each allowed directory.
        # Special case: bare directory names like "data" or "outputs"
        for allowed in allowed_dirs:
            if raw == Path(allowed.name):
                return allowed

            candidate = (allowed / raw).resolve()
            self._check_symlink(candidate)
            if self._is_contained(candidate, allowed_dirs):
                return candidate

        # If no allowed dir matches, raise
        raise PathTraversalError(
            f"Access denied ({operation}): '{filepath}' could not be "
            f"resolved within any allowed directory.",
            details={
                "path": filepath,
                "allowed": [str(d) for d in allowed_dirs],
            },
        )

    @staticmethod
    def _is_contained(resolved: Path, allowed_dirs: list[Path]) -> bool:
        """Check structural containment using ``is_relative_to``."""
        return any(resolved.is_relative_to(d) for d in allowed_dirs)

    @staticmethod
    def _check_symlink(path: Path) -> None:
        """Reject symlinks whose target escapes the sandbox.

        We resolve the path fully (which follows symlinks) before
        containment checks, so this is defense-in-depth: we also
        flag the *presence* of a symlink as a warning vector.
        """
        if path.is_symlink():
            raise PathTraversalError(
                f"Symlink detected: '{path}'. Symlinks are blocked as a "
                f"security precaution.",
                details={"path": str(path), "target": str(path.resolve())},
            )
