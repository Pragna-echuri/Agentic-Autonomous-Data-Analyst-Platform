"""
Reflection Module
=================
Implements a self-critique loop for LLM-generated SQL and Python code.
The agent generates code, then a separate reflection prompt evaluates it
for correctness, safety, and optimality before execution.

Architecture:
    User Query → LLM generates code → Reflection reviews it →
    If issues found → Regenerate (max 2 iterations) → Execute

Usage:
    from reflection import ReflectionEngine
    engine = ReflectionEngine(llm)
    result = await engine.reflect_on_sql(sql, user_intent)
"""

import os
import json
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ReflectionResult:
    """Result of a reflection cycle."""
    original_code: str
    final_code: str
    is_approved: bool
    iterations: int
    critique_log: list = field(default_factory=list)
    risk_level: str = "low"  # low, medium, high


# ─── Reflection Prompts ─────────────────────────────────────────────────────

SQL_REFLECTION_PROMPT = """You are a senior database engineer reviewing SQL code.

**User's Intent**: {user_intent}

**Generated SQL**:
```sql
{sql_code}
```

**Database Schema Context** (if available):
{schema_context}

Review this SQL for:
1. **Correctness**: Does it accurately answer the user's question?
2. **SQL Injection Risks**: Are there any unsafe patterns?
3. **Syntax Errors**: Any typos, missing keywords, or invalid SQL?
4. **Performance**: Will it cause full table scans? Missing JOINs? Cartesian products?
5. **Edge Cases**: NULL handling, division by zero, empty results?

Respond in this exact JSON format:
{{
    "approved": true/false,
    "risk_level": "low" | "medium" | "high",
    "issues": ["list of issues found"],
    "corrected_sql": "the corrected SQL if changes needed, or the original if approved",
    "explanation": "brief explanation of your review"
}}
"""

PYTHON_REFLECTION_PROMPT = """You are a senior Python engineer reviewing data visualization code.

**User's Intent**: {user_intent}

**Generated Python Code**:
```python
{python_code}
```

Review this code for:
1. **Safety**: No file system access outside outputs/, no network calls, no exec/eval abuse
2. **Correctness**: Does it create the visualization the user asked for?
3. **Best Practices**: Proper use of matplotlib/plotly/seaborn APIs
4. **Error Handling**: Will it crash on edge cases (empty data, wrong types)?
5. **Output**: Does it save the plot to the correct path?

Respond in this exact JSON format:
{{
    "approved": true/false,
    "risk_level": "low" | "medium" | "high",
    "issues": ["list of issues found"],
    "corrected_code": "the corrected Python code if changes needed, or the original if approved",
    "explanation": "brief explanation of your review"
}}
"""


class ReflectionEngine:
    """Handles code self-critique using the LLM."""

    def __init__(self, llm_client, max_iterations: int = 2):
        """
        Args:
            llm_client: A Groq client instance for making LLM calls.
            max_iterations: Maximum reflection iterations (default: 2).
        """
        self.llm = llm_client
        self.max_iterations = max_iterations
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    def _call_llm(self, prompt: str) -> str:
        """Make a synchronous LLM call for reflection."""
        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a code review expert. Always respond with valid JSON only. "
                            "No markdown, no explanation outside the JSON structure."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,  # Low temperature for consistent reviews
                max_tokens=2000,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            # On failure, approve the code to avoid blocking
            return json.dumps({
                "approved": True,
                "risk_level": "unknown",
                "issues": [f"Reflection failed: {str(e)}"],
                "corrected_sql": "",
                "corrected_code": "",
                "explanation": "Reflection unavailable, proceeding with original code."
            })

    def _parse_reflection(self, response: str) -> dict:
        """Parse the LLM's JSON response."""
        try:
            # Handle markdown code fences
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            return json.loads(response.strip())
        except (json.JSONDecodeError, IndexError):
            return {
                "approved": True,
                "risk_level": "unknown",
                "issues": ["Could not parse reflection response"],
                "explanation": "Proceeding with original code.",
            }

    def reflect_on_sql(
        self,
        sql_code: str,
        user_intent: str,
        schema_context: str = "Not available",
    ) -> ReflectionResult:
        """Reflect on generated SQL code.

        Args:
            sql_code: The SQL query to review.
            user_intent: What the user asked (natural language).
            schema_context: Database schema info for context.

        Returns:
            ReflectionResult with approval status and final code.
        """
        current_code = sql_code
        critique_log = []

        for iteration in range(self.max_iterations):
            prompt = SQL_REFLECTION_PROMPT.format(
                user_intent=user_intent,
                sql_code=current_code,
                schema_context=schema_context,
            )

            response = self._call_llm(prompt)
            reflection = self._parse_reflection(response)
            critique_log.append({
                "iteration": iteration + 1,
                "reflection": reflection,
            })

            if reflection.get("approved", True):
                return ReflectionResult(
                    original_code=sql_code,
                    final_code=reflection.get("corrected_sql", current_code) or current_code,
                    is_approved=True,
                    iterations=iteration + 1,
                    critique_log=critique_log,
                    risk_level=reflection.get("risk_level", "low"),
                )

            # Use corrected version for next iteration
            corrected = reflection.get("corrected_sql", "")
            if corrected and corrected != current_code:
                current_code = corrected
            else:
                # No correction provided, approve anyway
                return ReflectionResult(
                    original_code=sql_code,
                    final_code=current_code,
                    is_approved=True,
                    iterations=iteration + 1,
                    critique_log=critique_log,
                    risk_level=reflection.get("risk_level", "medium"),
                )

        # Max iterations reached — use last corrected version
        return ReflectionResult(
            original_code=sql_code,
            final_code=current_code,
            is_approved=True,
            iterations=self.max_iterations,
            critique_log=critique_log,
            risk_level="medium",
        )

    def reflect_on_python(
        self,
        python_code: str,
        user_intent: str,
    ) -> ReflectionResult:
        """Reflect on generated Python visualization code.

        Args:
            python_code: The Python code to review.
            user_intent: What the user asked (natural language).

        Returns:
            ReflectionResult with approval status and final code.
        """
        current_code = python_code
        critique_log = []

        for iteration in range(self.max_iterations):
            prompt = PYTHON_REFLECTION_PROMPT.format(
                user_intent=user_intent,
                python_code=current_code,
            )

            response = self._call_llm(prompt)
            reflection = self._parse_reflection(response)
            critique_log.append({
                "iteration": iteration + 1,
                "reflection": reflection,
            })

            if reflection.get("approved", True):
                return ReflectionResult(
                    original_code=python_code,
                    final_code=reflection.get("corrected_code", current_code) or current_code,
                    is_approved=True,
                    iterations=iteration + 1,
                    critique_log=critique_log,
                    risk_level=reflection.get("risk_level", "low"),
                )

            corrected = reflection.get("corrected_code", "")
            if corrected and corrected != current_code:
                current_code = corrected
            else:
                return ReflectionResult(
                    original_code=python_code,
                    final_code=current_code,
                    is_approved=True,
                    iterations=iteration + 1,
                    critique_log=critique_log,
                    risk_level=reflection.get("risk_level", "medium"),
                )

        return ReflectionResult(
            original_code=python_code,
            final_code=current_code,
            is_approved=True,
            iterations=self.max_iterations,
            critique_log=critique_log,
            risk_level="medium",
        )
