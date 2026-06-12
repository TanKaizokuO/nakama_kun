"""orchestration/test_parser.py — Parsers for pytest and unittest outputs."""

from __future__ import annotations

import re
from typing import Any


def parse_pytest_output(content: str) -> dict[str, Any] | None:
    """Parse pytest output to extract passed, failed, errors, skipped, and success."""
    summary_pattern = re.compile(
        r"={3,}\s*(.*?)\s*in\s+\d+.*?={3,}|={3,}\s*(.*?during collection.*?)\s*={3,}"
    )
    
    # We search from the bottom of the output
    lines = content.splitlines()
    summary_text = None
    for line in reversed(lines):
        if "====" in line and (
            "passed" in line
            or "failed" in line
            or "skipped" in line
            or "error" in line
            or "no tests ran" in line
        ):
            summary_text = line
            break
            
    if not summary_text:
        # Fallback to search in whole text
        match = summary_pattern.search(content)
        if match:
            summary_text = match.group(0)
            
    if not summary_text:
        return None
        
    passed = 0
    failed = 0
    errors = 0
    skipped = 0
    
    # Parse individual counts
    passed_match = re.search(r"(\d+)\s+passed", summary_text)
    if passed_match:
        passed = int(passed_match.group(1))
        
    failed_match = re.search(r"(\d+)\s+failed", summary_text)
    if failed_match:
        failed = int(failed_match.group(1))
        
    skipped_match = re.search(r"(\d+)\s+skipped", summary_text)
    if skipped_match:
        skipped = int(skipped_match.group(1))
        
    error_match = re.search(r"(\d+)\s+error(?:s)?", summary_text)
    if error_match:
        errors = int(error_match.group(1))
        
    # Check if there was collection failure
    if "error during collection" in summary_text or "errors during collection" in summary_text:
        collection_error_match = re.search(
            r"(\d+)\s+error(?:s)?\s+during\s+collection", summary_text
        )
        if collection_error_match:
            errors = int(collection_error_match.group(1))
        else:
            errors = max(errors, 1)

    success = (failed == 0 and errors == 0)
    if "no tests ran" in summary_text:
        success = (errors == 0)

    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "success": success,
    }


def parse_unittest_output(content: str) -> dict[str, Any] | None:
    """Parse unittest output to extract passed, failed, errors, skipped, and success."""
    return None


def parse_test_results(cmd: str, content: str) -> dict[str, Any] | None:
    """Parse command output for pytest or unittest results."""
    return None
