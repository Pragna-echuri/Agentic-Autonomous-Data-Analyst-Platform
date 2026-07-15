"""
Unit Tests — Security Sandbox
==============================
Tests for AST-based Python and SQL validation in ``security.sandbox``.
"""

from __future__ import annotations

import pytest

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent.resolve()))

from core.exceptions import SandboxViolationError, SQLInjectionError
from security.sandbox import CodeSandbox


@pytest.fixture
def sandbox() -> CodeSandbox:
    return CodeSandbox()


# ═══════════════════════════════════════════════════════════════════════
#  Python Validation — Should PASS
# ═══════════════════════════════════════════════════════════════════════

class TestPythonSafe:
    """Python code that should be accepted by the sandbox."""

    def test_simple_assignment(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_python("x = 1 + 2")

    def test_pandas_operations(self, sandbox: CodeSandbox) -> None:
        code = "import pandas as pd\ndf = pd.read_csv('data.csv')\ndf.describe()"
        sandbox.validate_python(code)

    def test_matplotlib_operations(self, sandbox: CodeSandbox) -> None:
        code = "import matplotlib.pyplot as plt\nplt.figure()\nplt.show()"
        # matplotlib is not blocked
        sandbox.validate_python(code)

    def test_math_operations(self, sandbox: CodeSandbox) -> None:
        code = "import math\nx = math.sqrt(16)"
        sandbox.validate_python(code)

    def test_json_operations(self, sandbox: CodeSandbox) -> None:
        code = "import json\ndata = json.loads('{}')"
        sandbox.validate_python(code)

    def test_list_comprehension(self, sandbox: CodeSandbox) -> None:
        code = "[x**2 for x in range(10)]"
        sandbox.validate_python(code)

    def test_function_definition(self, sandbox: CodeSandbox) -> None:
        code = "def add(a, b):\n    return a + b\nresult = add(1, 2)"
        sandbox.validate_python(code)

    def test_string_methods(self, sandbox: CodeSandbox) -> None:
        code = "text = 'hello world'\nupper = text.upper()"
        sandbox.validate_python(code)


# ═══════════════════════════════════════════════════════════════════════
#  Python Validation — Should BLOCK
# ═══════════════════════════════════════════════════════════════════════

class TestPythonBlocked:
    """Python code that should be rejected by the sandbox."""

    def test_import_os(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import os\nos.system('ls')")

    def test_import_subprocess(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import subprocess")

    def test_import_shutil(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import shutil")

    def test_import_socket(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import socket")

    def test_import_requests(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import requests")

    def test_from_os_import(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("from os import path")

    def test_eval_call(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("result = eval('1 + 2')")

    def test_exec_call(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("exec('import os')")

    def test_compile_call(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("compile('pass', '<string>', 'exec')")

    def test_dunder_import(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("__import__('os')")

    def test_os_system(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import os\nos.system('rm -rf /')")

    def test_subprocess_run(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import subprocess\nsubprocess.run(['ls'])")

    def test_open_write_mode(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("f = open('/etc/passwd', 'w')")

    def test_open_append_mode(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("f = open('file.txt', 'a')")

    def test_import_pickle(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import pickle")

    def test_import_multiprocessing(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("import multiprocessing")

    def test_syntax_error(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("def foo(")

    def test_globals_call(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SandboxViolationError):
            sandbox.validate_python("g = globals()")


# ═══════════════════════════════════════════════════════════════════════
#  SQL Validation — Should PASS
# ═══════════════════════════════════════════════════════════════════════

class TestSQLSafe:
    """SQL queries that should be accepted."""

    def test_simple_select(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly("SELECT * FROM users")

    def test_select_with_where(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly("SELECT id, name FROM users WHERE age > 25")

    def test_select_with_join(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly(
            "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        )

    def test_select_with_aggregation(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly(
            "SELECT department, AVG(salary) FROM employees GROUP BY department"
        )

    def test_with_cte(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly(
            "WITH top AS (SELECT * FROM sales LIMIT 10) SELECT * FROM top"
        )

    def test_explain(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly("EXPLAIN SELECT * FROM users")

    def test_select_with_subquery(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly(
            "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
        )

    def test_trailing_semicolon(self, sandbox: CodeSandbox) -> None:
        sandbox.validate_sql_readonly("SELECT 1;")


# ═══════════════════════════════════════════════════════════════════════
#  SQL Validation — Should BLOCK
# ═══════════════════════════════════════════════════════════════════════

class TestSQLBlocked:
    """SQL queries that should be rejected."""

    def test_drop_table(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("DROP TABLE users")

    def test_delete_from(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("DELETE FROM users WHERE id = 1")

    def test_insert_into(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("INSERT INTO users VALUES (1, 'test')")

    def test_update_table(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("UPDATE users SET name = 'hack'")

    def test_alter_table(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("ALTER TABLE users ADD COLUMN hack TEXT")

    def test_create_table(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("CREATE TABLE evil (id INT)")

    def test_multiple_statements(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("SELECT 1; DROP TABLE users")

    def test_comment_injection(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("-- SELECT 1\nDROP TABLE users")

    def test_block_comment_injection(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("/* harmless */ DROP TABLE users")

    def test_load_extension(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("SELECT LOAD_EXTENSION('evil.so')")

    def test_truncate(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("TRUNCATE TABLE users")

    def test_attach_database(self, sandbox: CodeSandbox) -> None:
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("ATTACH DATABASE '/etc/passwd' AS pwned")

    def test_empty_query(self, sandbox: CodeSandbox) -> None:
        # Empty queries should not pass as valid
        with pytest.raises(SQLInjectionError):
            sandbox.validate_sql_readonly("")
