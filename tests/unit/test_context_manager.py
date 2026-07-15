"""
Unit Tests — Context Manager
==============================
Tests for token-aware message trimming in ``memory.context_manager``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

from memory.context_manager import (
    estimate_messages_tokens,
    estimate_tokens,
    trim_messages_to_budget,
    truncate_to_budget,
)


# ═══════════════════════════════════════════════════════════════════════
#  Token Estimation
# ═══════════════════════════════════════════════════════════════════════

class TestTokenEstimation:
    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_string(self) -> None:
        # "hello" = 5 chars → 5 // 4 = 1 token
        assert estimate_tokens("hello") == 1

    def test_longer_string(self) -> None:
        # 100 chars → 25 tokens
        text = "x" * 100
        assert estimate_tokens(text) == 25

    def test_message_tokens(self) -> None:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        total = estimate_messages_tokens(messages)
        assert total > 0


# ═══════════════════════════════════════════════════════════════════════
#  Truncation
# ═══════════════════════════════════════════════════════════════════════

class TestTruncation:
    def test_no_truncation_needed(self) -> None:
        text = "Short text"
        result = truncate_to_budget(text, max_tokens=100)
        assert result == text

    def test_truncation_applied(self) -> None:
        text = "x" * 10000
        result = truncate_to_budget(text, max_tokens=10)
        # 10 tokens × 4 chars = 40 chars max
        assert len(result) < len(text)
        assert "Truncated" in result

    def test_truncation_preserves_start(self) -> None:
        text = "STARTMARKER" + "x" * 10000
        result = truncate_to_budget(text, max_tokens=10)
        assert result.startswith("STARTMARKER")


# ═══════════════════════════════════════════════════════════════════════
#  Message Trimming
# ═══════════════════════════════════════════════════════════════════════

class TestMessageTrimming:
    def test_no_trimming_short_history(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = trim_messages_to_budget(messages, max_total_tokens=10000)
        assert len(result) == 2

    def test_preserves_system_message(self) -> None:
        messages = [
            {"role": "system", "content": "You are an assistant. " * 100},
        ]
        for i in range(20):
            messages.append({"role": "user", "content": f"Question {i} " * 50})
            messages.append({"role": "assistant", "content": f"Answer {i} " * 50})

        result = trim_messages_to_budget(messages, max_total_tokens=100)
        assert result[0]["role"] == "system"

    def test_preserves_recent_messages(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(20):
            messages.append({"role": "user", "content": f"Q{i} " * 50})
            messages.append({"role": "assistant", "content": f"A{i} " * 50})

        result = trim_messages_to_budget(messages, max_total_tokens=200)
        # Last message should be preserved
        assert result[-1]["content"].startswith("A19")

    def test_removes_middle_messages(self) -> None:
        messages = [
            {"role": "system", "content": "sys"},
        ]
        for i in range(10):
            messages.append({"role": "user", "content": f"Q{i} " * 100})
            messages.append({"role": "assistant", "content": f"A{i} " * 100})

        original_count = len(messages)
        result = trim_messages_to_budget(messages, max_total_tokens=200)
        assert len(result) < original_count

    def test_single_message_passthrough(self) -> None:
        messages = [{"role": "system", "content": "sys"}]
        result = trim_messages_to_budget(messages, max_total_tokens=1)
        assert len(result) == 1
