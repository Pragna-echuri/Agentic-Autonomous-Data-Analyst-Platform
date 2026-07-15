"""
Context Manager — Token-Aware Compression
==========================================
Manages the LLM context budget by:

* Tracking approximate token counts for conversation history.
* Truncating tool outputs that exceed the per-message budget.
* Summarising long conversation histories via the LLM.
* Enforcing hard limits to prevent context-window overflows.

Token counting uses a 1 token ≈ 4 characters heuristic (conservative
for English text with Llama tokenisers).
"""

from __future__ import annotations

from typing import Any

from core.config import Settings, get_settings
from observability.logger import get_logger

log = get_logger(__name__)

# Conservative heuristic: 1 token ≈ 4 characters
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count using character-length heuristic."""
    return len(text) // _CHARS_PER_TOKEN


def truncate_to_budget(
    text: str,
    max_tokens: int | None = None,
) -> str:
    """Truncate text to fit within a token budget.

    Parameters
    ----------
    text:
        The text to (potentially) truncate.
    max_tokens:
        Maximum tokens allowed. Defaults to config's ``max_context_tokens``.

    Returns
    -------
    str
        Truncated text with a notice if any truncation occurred.
    """
    settings = get_settings()
    budget = max_tokens or settings.max_context_tokens
    max_chars = budget * _CHARS_PER_TOKEN

    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    notice = (
        f"\n\n... [Truncated: showing ~{budget} tokens of "
        f"~{estimate_tokens(text)} total] ..."
    )
    return truncated + notice


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across a message list."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        # Account for role and structural overhead
        total += 4
    return total


def trim_messages_to_budget(
    messages: list[dict[str, Any]],
    max_total_tokens: int = 20_000,
) -> list[dict[str, Any]]:
    """Trim older messages if the conversation exceeds the token budget.

    Always preserves the system message (index 0) and the last user
    message. Middle messages are removed from oldest to newest.

    Parameters
    ----------
    messages:
        The full conversation message list.
    max_total_tokens:
        Maximum total tokens allowed for the message list.

    Returns
    -------
    list
        Trimmed message list.
    """
    if len(messages) <= 2:
        return messages

    total = estimate_messages_tokens(messages)
    if total <= max_total_tokens:
        return messages

    # Always keep: system (0), and last 4 messages (recent context)
    keep_start = messages[:1]  # system
    keep_end = messages[-4:]   # recent context
    middle = messages[1:-4]

    # Remove from oldest middle messages
    trimmed: list[dict[str, Any]] = list(keep_start)
    remaining_budget = max_total_tokens - estimate_messages_tokens(
        keep_start + keep_end
    )

    for msg in reversed(middle):
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if remaining_budget >= msg_tokens:
            trimmed.insert(1, msg)
            remaining_budget -= msg_tokens

    trimmed.extend(keep_end)

    removed = len(messages) - len(trimmed)
    if removed > 0:
        log.info(
            "messages_trimmed",
            removed=removed,
            original=len(messages),
            final=len(trimmed),
        )

    return trimmed
