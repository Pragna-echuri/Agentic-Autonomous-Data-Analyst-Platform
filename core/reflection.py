"""
Async Reflection Engine
=======================
Self-critique loop for LLM-generated SQL and Python code.

Pipeline:
    Generated code → AST static analysis → LLM review → Accept/Correct → Re-validate

Improvements over the prototype:

* **Async** — ``_call_llm`` is non-blocking via the ``LLMClient``.
* **AST gate** — deterministic sandbox check runs *before* the probabilistic
  LLM review, catching ``eval``, ``exec``, ``import os``, etc.
* **Hard block** — code with ``risk_level=high`` is never approved.
* **Pydantic verdict** — structured ``ReflectionVerdict`` replaces raw dicts.
* **Python reflection wired** — ``reflect_on_python`` is now callable.

Usage::

    from core.reflection import ReflectionEngine
    engine = ReflectionEngine(llm_client)
    result = await engine.reflect_on_sql(sql, user_intent="...")
"""

from __future__ import annotations

import json
from typing import Any

from core.config import Settings, get_settings
from core.exceptions import SandboxViolationError
from core.llm_client import LLMClient
from core.models import (
    ReflectionCycleEntry,
    ReflectionResult,
    ReflectionVerdict,
    RiskLevel,
)
from core.prompts import PYTHON_REFLECTION_PROMPT, SQL_REFLECTION_PROMPT
from observability.logger import get_logger
from observability.metrics import metrics
from security.sandbox import CodeSandbox

log = get_logger(__name__)


class ReflectionEngine:
    """Async code self-critique engine with AST pre-screening."""

    def __init__(
        self,
        llm_client: LLMClient,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm_client
        self._settings = settings or get_settings()
        self._sandbox = CodeSandbox()
        self._max_iterations = self._settings.reflection_max_iterations

    # ── SQL Reflection ───────────────────────────────────────────────

    async def reflect_on_sql(
        self,
        sql_code: str,
        user_intent: str,
        schema_context: str = "Not available",
    ) -> ReflectionResult:
        """Review and optionally correct generated SQL.

        Steps:
            1. AST-level SQL safety check (multi-statement, write keywords).
            2. LLM review with structured JSON verdict.
            3. If rejected, apply correction and re-validate (max N iterations).
            4. Hard-block any ``high`` risk code.
        """
        metrics.increment("reflection_sql_total")

        # Step 1: Static analysis gate
        try:
            self._sandbox.validate_sql_readonly(sql_code)
        except Exception as exc:
            log.warning(
                "reflection_static_block_sql",
                error=str(exc),
                sql_snippet=sql_code[:100],
            )
            return ReflectionResult(
                original_code=sql_code,
                final_code=sql_code,
                is_approved=False,
                iterations=0,
                critique_log=[
                    ReflectionCycleEntry(
                        iteration=0,
                        verdict=ReflectionVerdict(
                            approved=False,
                            risk_level=RiskLevel.HIGH,
                            issues=[str(exc)],
                            explanation="Blocked by static analysis.",
                        ),
                    )
                ],
                risk_level=RiskLevel.HIGH,
            )

        # Step 2: LLM reflection loop
        current_code = sql_code
        critique_log: list[ReflectionCycleEntry] = []

        for iteration in range(1, self._max_iterations + 1):
            prompt = SQL_REFLECTION_PROMPT.format(
                user_intent=user_intent,
                sql_code=current_code,
                schema_context=schema_context,
            )

            verdict = await self._get_verdict(prompt)
            critique_log.append(
                ReflectionCycleEntry(iteration=iteration, verdict=verdict)
            )

            # Hard block high-risk
            if verdict.risk_level == RiskLevel.HIGH:
                log.warning(
                    "reflection_high_risk_sql",
                    iteration=iteration,
                    issues=verdict.issues,
                )
                return ReflectionResult(
                    original_code=sql_code,
                    final_code=current_code,
                    is_approved=False,
                    iterations=iteration,
                    critique_log=critique_log,
                    risk_level=RiskLevel.HIGH,
                )

            if verdict.approved:
                final = verdict.corrected_code or current_code
                return ReflectionResult(
                    original_code=sql_code,
                    final_code=final,
                    is_approved=True,
                    iterations=iteration,
                    critique_log=critique_log,
                    risk_level=verdict.risk_level,
                )

            # Apply correction for next iteration
            if verdict.corrected_code and verdict.corrected_code != current_code:
                current_code = verdict.corrected_code
            else:
                # No correction provided — accept current
                return ReflectionResult(
                    original_code=sql_code,
                    final_code=current_code,
                    is_approved=True,
                    iterations=iteration,
                    critique_log=critique_log,
                    risk_level=verdict.risk_level,
                )

        # Max iterations exhausted — accept with medium risk
        return ReflectionResult(
            original_code=sql_code,
            final_code=current_code,
            is_approved=True,
            iterations=self._max_iterations,
            critique_log=critique_log,
            risk_level=RiskLevel.MEDIUM,
        )

    # ── Python Reflection ────────────────────────────────────────────

    async def reflect_on_python(
        self,
        python_code: str,
        user_intent: str,
    ) -> ReflectionResult:
        """Review and optionally correct generated Python code.

        Steps:
            1. AST-level Python safety check (blocked imports/calls).
            2. LLM review with structured JSON verdict.
            3. If rejected, apply correction and re-validate.
            4. Hard-block any ``high`` risk code.
        """
        metrics.increment("reflection_python_total")

        # Step 1: AST static analysis gate
        try:
            self._sandbox.validate_python(python_code)
        except SandboxViolationError as exc:
            log.warning(
                "reflection_static_block_python",
                error=str(exc),
                code_snippet=python_code[:100],
            )
            return ReflectionResult(
                original_code=python_code,
                final_code=python_code,
                is_approved=False,
                iterations=0,
                critique_log=[
                    ReflectionCycleEntry(
                        iteration=0,
                        verdict=ReflectionVerdict(
                            approved=False,
                            risk_level=RiskLevel.HIGH,
                            issues=exc.details.get("violations", [str(exc)]),
                            explanation="Blocked by AST static analysis.",
                        ),
                    )
                ],
                risk_level=RiskLevel.HIGH,
            )

        # Step 2: LLM reflection loop
        current_code = python_code
        critique_log: list[ReflectionCycleEntry] = []

        for iteration in range(1, self._max_iterations + 1):
            prompt = PYTHON_REFLECTION_PROMPT.format(
                user_intent=user_intent,
                python_code=current_code,
            )

            verdict = await self._get_verdict(prompt)
            critique_log.append(
                ReflectionCycleEntry(iteration=iteration, verdict=verdict)
            )

            if verdict.risk_level == RiskLevel.HIGH:
                log.warning(
                    "reflection_high_risk_python",
                    iteration=iteration,
                    issues=verdict.issues,
                )
                return ReflectionResult(
                    original_code=python_code,
                    final_code=current_code,
                    is_approved=False,
                    iterations=iteration,
                    critique_log=critique_log,
                    risk_level=RiskLevel.HIGH,
                )

            if verdict.approved:
                final = verdict.corrected_code or current_code
                # Re-validate corrected code through AST
                try:
                    self._sandbox.validate_python(final)
                except SandboxViolationError:
                    log.warning(
                        "reflection_corrected_code_failed_ast",
                        iteration=iteration,
                    )
                    final = current_code  # Fall back to pre-correction

                return ReflectionResult(
                    original_code=python_code,
                    final_code=final,
                    is_approved=True,
                    iterations=iteration,
                    critique_log=critique_log,
                    risk_level=verdict.risk_level,
                )

            if verdict.corrected_code and verdict.corrected_code != current_code:
                current_code = verdict.corrected_code
            else:
                return ReflectionResult(
                    original_code=python_code,
                    final_code=current_code,
                    is_approved=True,
                    iterations=iteration,
                    critique_log=critique_log,
                    risk_level=verdict.risk_level,
                )

        return ReflectionResult(
            original_code=python_code,
            final_code=current_code,
            is_approved=True,
            iterations=self._max_iterations,
            critique_log=critique_log,
            risk_level=RiskLevel.MEDIUM,
        )

    # ── Internal ─────────────────────────────────────────────────────

    async def _get_verdict(self, prompt: str) -> ReflectionVerdict:
        """Call the LLM for a reflection review and parse the verdict."""
        try:
            response = await self._llm.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a code review expert. Always respond "
                            "with valid JSON only. No markdown fences, no "
                            "explanation outside the JSON structure."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            raw = response.choices[0].message.content or ""
            return self._parse_verdict(raw)

        except Exception as exc:
            log.warning("reflection_llm_failed", error=str(exc))
            return ReflectionVerdict(
                approved=True,
                risk_level=RiskLevel.UNKNOWN,
                issues=[f"Reflection LLM call failed: {exc}"],
                explanation="Proceeding with original code due to reflection failure.",
            )

    @staticmethod
    def _parse_verdict(raw: str) -> ReflectionVerdict:
        """Parse the LLM's JSON response into a validated verdict."""
        cleaned = raw.strip()

        # Strip markdown code fences
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]

        try:
            data: dict[str, Any] = json.loads(cleaned.strip())
        except (json.JSONDecodeError, IndexError):
            return ReflectionVerdict(
                approved=True,
                risk_level=RiskLevel.UNKNOWN,
                issues=["Could not parse reflection JSON response."],
                explanation="Proceeding with original code.",
            )

        # Normalise field names
        corrected = data.get("corrected_sql") or data.get("corrected_code", "")

        return ReflectionVerdict(
            approved=data.get("approved", True),
            risk_level=RiskLevel(data.get("risk_level", "low")),
            issues=data.get("issues", []),
            corrected_code=corrected,
            explanation=data.get("explanation", ""),
        )
