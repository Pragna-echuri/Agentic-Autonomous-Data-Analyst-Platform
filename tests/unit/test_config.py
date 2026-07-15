"""
Unit Tests — Configuration
============================
Tests for ``core.config`` Settings validation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

from pydantic import ValidationError

from core.config import Settings


class TestSettingsDefaults:
    def test_default_model(self) -> None:
        s = Settings()
        assert "llama" in s.groq_model.lower() or "70b" in s.groq_model

    def test_default_temperature(self) -> None:
        s = Settings()
        assert 0.0 <= s.llm_temperature <= 2.0

    def test_default_max_tokens(self) -> None:
        s = Settings()
        assert 256 <= s.llm_max_tokens <= 32768

    def test_default_max_query_rows(self) -> None:
        s = Settings()
        assert s.max_query_rows == 100

    def test_default_log_level(self) -> None:
        s = Settings()
        assert s.log_level == "INFO"

    def test_default_log_format(self) -> None:
        s = Settings()
        assert s.log_format in ("json", "console")


class TestSettingsValidation:
    def test_temperature_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Settings(llm_temperature=5.0)

    def test_negative_temperature(self) -> None:
        with pytest.raises(ValidationError):
            Settings(llm_temperature=-1.0)

    def test_max_tokens_too_low(self) -> None:
        with pytest.raises(ValidationError):
            Settings(llm_max_tokens=10)

    def test_max_tokens_too_high(self) -> None:
        with pytest.raises(ValidationError):
            Settings(llm_max_tokens=100_000)

    def test_port_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Settings(api_port=0)

    def test_valid_port(self) -> None:
        s = Settings(api_port=3000)
        assert s.api_port == 3000


class TestSettingsPaths:
    def test_project_root_resolved(self) -> None:
        s = Settings()
        assert s.project_root is not None
        assert s.project_root.is_absolute()

    def test_data_dir_resolved(self) -> None:
        s = Settings()
        assert s.data_dir is not None

    def test_outputs_dir_created(self) -> None:
        s = Settings()
        assert s.outputs_dir.exists()

    def test_python_executable(self) -> None:
        s = Settings()
        assert s.python_executable
        assert "python" in s.python_executable.lower() or "python" in Path(s.python_executable).stem.lower()

    def test_resolved_db_path(self) -> None:
        s = Settings()
        assert s.resolved_db_path.is_absolute()


class TestSettingsExtensions:
    def test_upload_extensions(self) -> None:
        s = Settings()
        assert ".csv" in s.allowed_upload_extensions
        assert ".xlsx" in s.allowed_upload_extensions
        assert ".exe" not in s.allowed_upload_extensions

    def test_write_extensions(self) -> None:
        s = Settings()
        assert ".md" in s.allowed_write_extensions
        assert ".png" in s.allowed_write_extensions
        assert ".py" not in s.allowed_write_extensions
