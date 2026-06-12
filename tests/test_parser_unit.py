from __future__ import annotations

from nakama_kun.orchestration.test_parser import (
    parse_pytest_output,
    parse_test_results,
    parse_unittest_output,
)


def test_parse_pytest_all_pass() -> None:
    content = """
============================= test session starts ==============================
collected 10 items

test_module.py ..........                                                 [100%]
============================== 10 passed in 0.12s ==============================
"""
    res = parse_pytest_output(content)
    assert res is not None
    assert res["passed"] == 10
    assert res["failed"] == 0
    assert res["errors"] == 0
    assert res["skipped"] == 0
    assert res["success"] is True


def test_parse_pytest_with_failures_and_errors() -> None:
    content = """
============================= test session starts ==============================
collected 15 items

test_module.py .F.E.S...xx....                                            [100%]
=================== 12 passed, 1 failed, 1 skipped, 1 error in 1.45s ===================
"""
    res = parse_pytest_output(content)
    assert res is not None
    assert res["passed"] == 12
    assert res["failed"] == 1
    assert res["errors"] == 1
    assert res["skipped"] == 1
    assert res["success"] is False


def test_parse_pytest_collection_error() -> None:
    content = """
============================= test session starts ==============================
ImportError: cannot import name 'nonexistent'
=========================== 1 error during collection ===========================
"""
    res = parse_pytest_output(content)
    assert res is not None
    assert res["passed"] == 0
    assert res["failed"] == 0
    assert res["errors"] == 1
    assert res["success"] is False


def test_parse_unittest_ok() -> None:
    content = """
Ran 5 tests in 0.002s

OK
"""
    res = parse_unittest_output(content)
    assert res is not None
    assert res["passed"] == 5
    assert res["failed"] == 0
    assert res["errors"] == 0
    assert res["skipped"] == 0
    assert res["success"] is True


def test_parse_unittest_ok_with_skipped() -> None:
    content = """
Ran 8 tests in 0.005s

OK (skipped=3)
"""
    res = parse_unittest_output(content)
    assert res is not None
    assert res["passed"] == 5
    assert res["failed"] == 0
    assert res["errors"] == 0
    assert res["skipped"] == 3
    assert res["success"] is True


def test_parse_unittest_failed() -> None:
    content = """
Ran 12 tests in 0.020s

FAILED (failures=2, errors=1, skipped=1)
"""
    res = parse_unittest_output(content)
    assert res is not None
    assert res["passed"] == 8
    assert res["failed"] == 2
    assert res["errors"] == 1
    assert res["skipped"] == 1
    assert res["success"] is False


def test_parse_non_test_output() -> None:
    content = """
total 24
drwxr-xr-x 4 user group 4096 Jun 12 10:00 src
-rw-r--r-- 1 user group 1024 Jun 12 10:00 pyproject.toml
"""
    assert parse_test_results("ls -la", content) is None
