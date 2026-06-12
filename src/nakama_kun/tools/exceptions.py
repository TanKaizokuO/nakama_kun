"""
tools/exceptions.py — Typed exceptions for the nakama_kun tool layer.

All tool exceptions inherit from ToolError so callers can catch them
with a single clause while still being able to discriminate sub-types.
"""

from __future__ import annotations


class ToolError(RuntimeError):
    """Base class for all errors raised by the tools package."""


class PathEscapeError(ToolError):
    """Raised when a requested path resolves outside the workspace root."""


class CommandTimeoutError(ToolError):
    """Raised when a shell command exceeds the allowed execution time."""


class UnknownToolError(ToolError):
    """Raised when the ToolRouter receives a tool name that is not registered."""
