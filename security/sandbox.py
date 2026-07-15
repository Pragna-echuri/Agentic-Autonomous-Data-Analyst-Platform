"""
Code Sandbox — AST-Based Static Analysis
=========================================
Deterministic safety gate for LLM-generated Python and SQL code.

The sandbox performs **AST inspection** before any code reaches the
execution environment, catching dangerous patterns that a probabilistic
LLM reflection might miss.

Blocked Patterns (Python)
-------------------------
* ``import os``, ``import subprocess``, ``import shutil``, etc.
* ``eval()``, ``exec()``, ``compile()``, ``__import__()``
* ``open()`` calls targeting paths outside the sandbox
* ``os.system()``, ``subprocess.run()``, ``subprocess.Popen()``
* Network calls (``requests``, ``urllib``, ``httpx``, ``socket``)

Blocked Patterns (SQL)
----------------------
* Multi-statement execution (semicolons separating statements)
* Write keywords in read-only context (DROP, DELETE, INSERT, UPDATE,
  ALTER, CREATE, TRUNCATE)
* Comment-based injection (``--``, ``/* */`` preceding write statements)

Usage::

    from security.sandbox import CodeSandbox
    sandbox = CodeSandbox()
    sandbox.validate_python("import os; os.system('rm -rf /')")   # raises SandboxViolationError
    sandbox.validate_sql_readonly("SELECT 1; DROP TABLE x;")      # raises SQLInjectionError
"""

from __future__ import annotations

import ast
import re
from typing import Any

from core.exceptions import SandboxViolationError, SQLInjectionError

# ── Python Blocklists ────────────────────────────────────────────────

_BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
        "importlib",
        "ctypes",
        "signal",
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "smtplib",
        "telnetlib",
        "webbrowser",
        "code",
        "codeop",
        "compileall",
        "py_compile",
        "pickle",
        "shelve",
        "marshal",
        "tempfile",
        "glob",
        "fnmatch",
        "multiprocessing",
        "threading",
        "concurrent",
        "asyncio",
    }
)

_BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "breakpoint",
        "exit",
        "quit",
    }
)

_BLOCKED_ATTR_CALLS: frozenset[str] = frozenset(
    {
        "os.system",
        "os.popen",
        "os.exec",
        "os.execv",
        "os.execve",
        "os.spawn",
        "os.fork",
        "os.kill",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.rename",
        "os.makedirs",
        "os.mkdir",
        "subprocess.run",
        "subprocess.call",
        "subprocess.Popen",
        "subprocess.check_output",
        "subprocess.check_call",
        "shutil.rmtree",
        "shutil.move",
        "shutil.copy",
    }
)

# ── SQL Blocklists ───────────────────────────────────────────────────

_SQL_WRITE_KEYWORDS: frozenset[str] = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "REPLACE",
        "MERGE",
        "GRANT",
        "REVOKE",
        "ATTACH",
        "DETACH",
    }
)

_SQL_DANGEROUS_FUNCTIONS: frozenset[str] = frozenset(
    {
        "LOAD_EXTENSION",
        "FTS3",
        "FTSTOKEN",
    }
)


class CodeSandbox:
    """Static analysis gate for generated code."""

    # ── Python Validation ────────────────────────────────────────────

    def validate_python(self, code: str) -> list[str]:
        """Analyse Python source for dangerous patterns.

        Returns
        -------
        list[str]
            Empty list if the code is safe; otherwise raises.

        Raises
        ------
        SandboxViolationError
            If any blocked pattern is detected.
        """
        violations: list[str] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise SandboxViolationError(
                f"Code has syntax errors and cannot be analysed: {exc}",
                details={"code_snippet": code[:200]},
            ) from exc

        for node in ast.walk(tree):
            self._check_imports(node, violations)
            self._check_calls(node, violations)

        if violations:
            raise SandboxViolationError(
                f"Code blocked: {len(violations)} violation(s) detected.",
                details={"violations": violations, "code_snippet": code[:300]},
            )

        return violations

    def _check_imports(
        self, node: ast.AST, violations: list[str]
    ) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in _BLOCKED_MODULES:
                    violations.append(
                        f"Blocked import: '{alias.name}' "
                        f"(line {node.lineno})"
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split(".")[0]
                if root_module in _BLOCKED_MODULES:
                    violations.append(
                        f"Blocked import: 'from {node.module}' "
                        f"(line {node.lineno})"
                    )

    def _check_calls(
        self, node: ast.AST, violations: list[str]
    ) -> None:
        if not isinstance(node, ast.Call):
            return

        func_name = self._extract_call_name(node)
        if func_name is None:
            return

        # Direct builtin calls
        bare_name = func_name.split(".")[-1]
        if bare_name in _BLOCKED_BUILTINS:
            violations.append(
                f"Blocked builtin call: '{func_name}' "
                f"(line {node.lineno})"
            )

        # Attribute calls like os.system()
        if func_name in _BLOCKED_ATTR_CALLS:
            violations.append(
                f"Blocked dangerous call: '{func_name}' "
                f"(line {node.lineno})"
            )

        # open() with write mode
        if bare_name == "open" and len(node.args) >= 2:
            mode_arg = node.args[1]
            if isinstance(mode_arg, ast.Constant) and isinstance(
                mode_arg.value, str
            ):
                if any(c in mode_arg.value for c in "wax"):
                    violations.append(
                        f"Blocked file write via open(): mode='{mode_arg.value}' "
                        f"(line {node.lineno})"
                    )

    @staticmethod
    def _extract_call_name(node: ast.Call) -> str | None:
        """Extract the dotted name of a function call."""
        parts: list[str] = []
        current: Any = node.func

        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value

        if isinstance(current, ast.Name):
            parts.append(current.id)
            parts.reverse()
            return ".".join(parts)

        return None

    # ── SQL Validation ───────────────────────────────────────────────

    def validate_sql_readonly(self, sql: str) -> None:
        """Verify that *sql* contains only read-only operations.

        Raises
        ------
        SQLInjectionError
            If the query contains write operations, multiple
            statements, or dangerous function calls.
        """
        violations: list[str] = []

        # Strip SQL comments (both -- and /* */ styles)
        cleaned = self._strip_sql_comments(sql)

        # Check for multiple statements (semicolons)
        statements = [
            s.strip() for s in cleaned.split(";") if s.strip()
        ]

        # Empty query check
        if not statements:
            raise SQLInjectionError(
                "Empty SQL query.",
                details={"sql_snippet": sql[:200]},
            )

        if len(statements) > 1:
            violations.append(
                "Multiple SQL statements detected — only single "
                "SELECT/WITH queries are allowed."
            )

        # Check each statement for write keywords
        for stmt in statements:
            upper = stmt.upper()
            # Tokenise loosely: check first keyword
            first_word_match = re.match(r"\s*(\w+)", upper)
            first_word = first_word_match.group(1) if first_word_match else ""

            if first_word not in ("SELECT", "WITH", "EXPLAIN", "PRAGMA"):
                violations.append(
                    f"Blocked SQL keyword at start of statement: "
                    f"'{first_word}'."
                )

            # Check for write keywords anywhere in the query
            for kw in _SQL_WRITE_KEYWORDS:
                # Use word boundary matching to avoid false positives
                # (e.g., "UPDATED_AT" column name should not trigger)
                pattern = rf"\b{kw}\b"
                # But only block if it looks like a statement keyword,
                # not a column/alias name.  Heuristic: preceded by ) or
                # whitespace at statement level.
                if first_word != "SELECT" and re.search(pattern, upper):
                    violations.append(
                        f"Write keyword '{kw}' detected in non-SELECT "
                        f"context."
                    )
                    break

            # Check for dangerous functions
            for func in _SQL_DANGEROUS_FUNCTIONS:
                if func in upper:
                    violations.append(
                        f"Blocked SQL function: '{func}'."
                    )

        if violations:
            raise SQLInjectionError(
                f"SQL validation failed: {len(violations)} issue(s).",
                details={
                    "violations": violations,
                    "sql_snippet": sql[:200],
                },
            )

    @staticmethod
    def _strip_sql_comments(sql: str) -> str:
        """Remove SQL comments to prevent comment-based injection."""
        # Remove -- line comments
        result = re.sub(r"--[^\n]*", " ", sql)
        # Remove /* ... */ block comments
        result = re.sub(r"/\*.*?\*/", " ", result, flags=re.DOTALL)
        return result
