"""
Unit Tests — Path Validator
============================
Tests for filesystem sandbox enforcement in ``security.path_validator``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

from core.exceptions import PathTraversalError, SecurityError
from security.path_validator import PathValidator


@pytest.fixture
def validator(tmp_path: Path) -> PathValidator:
    """Create a PathValidator with temp directories as the sandbox."""
    data_dir = tmp_path / "data"
    outputs_dir = tmp_path / "outputs"
    data_dir.mkdir()
    outputs_dir.mkdir()

    # Create some test files
    (data_dir / "sample.csv").write_text("a,b\n1,2\n")
    (data_dir / "test.json").write_text('{"key": "value"}')
    (outputs_dir / "report.md").write_text("# Report")

    return PathValidator(
        allowed_read_dirs=[data_dir, outputs_dir],
        allowed_write_dirs=[outputs_dir],
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def outputs_dir(tmp_path: Path) -> Path:
    return tmp_path / "outputs"


# ═══════════════════════════════════════════════════════════════════════
#  Read Path — Should PASS
# ═══════════════════════════════════════════════════════════════════════

class TestReadPathSafe:
    def test_relative_file_in_data(self, validator: PathValidator, data_dir: Path) -> None:
        resolved = validator.resolve_read_path("sample.csv")
        assert resolved == data_dir / "sample.csv"

    def test_absolute_path_in_data(self, validator: PathValidator, data_dir: Path) -> None:
        resolved = validator.resolve_read_path(str(data_dir / "sample.csv"))
        assert resolved == data_dir / "sample.csv"

    def test_file_in_outputs(self, validator: PathValidator, outputs_dir: Path) -> None:
        resolved = validator.resolve_read_path(str(outputs_dir / "report.md"))
        assert resolved == outputs_dir / "report.md"

    def test_is_safe_read_true(self, validator: PathValidator) -> None:
        assert validator.is_safe_read("sample.csv") is True


# ═══════════════════════════════════════════════════════════════════════
#  Read Path — Should BLOCK
# ═══════════════════════════════════════════════════════════════════════

class TestReadPathBlocked:
    def test_path_traversal(self, validator: PathValidator) -> None:
        with pytest.raises(PathTraversalError):
            validator.resolve_read_path("../../etc/passwd")

    def test_absolute_path_outside(self, validator: PathValidator) -> None:
        with pytest.raises(PathTraversalError):
            validator.resolve_read_path("/etc/passwd")

    def test_is_safe_read_false(self, validator: PathValidator) -> None:
        assert validator.is_safe_read("../../etc/passwd") is False

    def test_windows_absolute_outside(self, validator: PathValidator) -> None:
        with pytest.raises((PathTraversalError, PermissionError)):
            validator.resolve_read_path("C:\\Users\\nonexistent\\secrets.txt")


# ═══════════════════════════════════════════════════════════════════════
#  Write Path — Should PASS
# ═══════════════════════════════════════════════════════════════════════

class TestWritePathSafe:
    def test_write_md_to_outputs(self, validator: PathValidator, outputs_dir: Path) -> None:
        resolved = validator.resolve_write_path(str(outputs_dir / "new_report.md"))
        assert resolved == outputs_dir / "new_report.md"

    def test_write_csv_to_outputs(self, validator: PathValidator, outputs_dir: Path) -> None:
        resolved = validator.resolve_write_path(str(outputs_dir / "export.csv"))
        assert resolved == outputs_dir / "export.csv"

    def test_write_png_to_outputs(self, validator: PathValidator, outputs_dir: Path) -> None:
        resolved = validator.resolve_write_path(str(outputs_dir / "chart.png"))
        assert resolved == outputs_dir / "chart.png"

    def test_is_safe_write_true(self, validator: PathValidator, outputs_dir: Path) -> None:
        assert validator.is_safe_write(str(outputs_dir / "test.json")) is True


# ═══════════════════════════════════════════════════════════════════════
#  Write Path — Should BLOCK
# ═══════════════════════════════════════════════════════════════════════

class TestWritePathBlocked:
    def test_write_to_data_dir(self, validator: PathValidator, data_dir: Path) -> None:
        with pytest.raises(PathTraversalError):
            validator.resolve_write_path(str(data_dir / "hack.csv"))

    def test_write_outside_sandbox(self, validator: PathValidator) -> None:
        with pytest.raises(PathTraversalError):
            validator.resolve_write_path("/tmp/evil.sh")

    def test_write_blocked_extension(self, validator: PathValidator, outputs_dir: Path) -> None:
        with pytest.raises(SecurityError):
            validator.resolve_write_path(str(outputs_dir / "malware.exe"))

    def test_write_blocked_py_extension(self, validator: PathValidator, outputs_dir: Path) -> None:
        with pytest.raises(SecurityError):
            validator.resolve_write_path(str(outputs_dir / "script.py"))

    def test_write_blocked_sh_extension(self, validator: PathValidator, outputs_dir: Path) -> None:
        with pytest.raises(SecurityError):
            validator.resolve_write_path(str(outputs_dir / "run.sh"))

    def test_is_safe_write_false(self, validator: PathValidator) -> None:
        assert validator.is_safe_write("/tmp/evil.sh") is False


# ═══════════════════════════════════════════════════════════════════════
#  Symlink Rejection
# ═══════════════════════════════════════════════════════════════════════

class TestSymlinkRejection:
    def test_symlink_blocked(self, validator: PathValidator, data_dir: Path, tmp_path: Path) -> None:
        """Symlinks pointing outside the sandbox should be rejected."""
        target = tmp_path / "outside_secret.txt"
        target.write_text("secret data")
        link = data_dir / "sneaky_link.csv"

        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        with pytest.raises(PathTraversalError):
            validator.resolve_read_path(str(link))
