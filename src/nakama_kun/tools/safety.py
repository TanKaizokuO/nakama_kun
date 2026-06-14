"""
tools/safety.py — Workspace path-safety guardrails for file tools.

Every file-based tool must call ``assert_within_workspace`` before performing
any I/O.  The check resolves both paths fully (following symlinks) and raises
``PathEscapeError`` if the target lies outside the declared workspace root.
"""

from __future__ import annotations

from pathlib import Path

from nakama_kun.tools.exceptions import PathEscapeError


def assert_within_workspace(path: str | Path, workspace_root: str | Path) -> Path:
    """Resolve *path* and verify it is contained within *workspace_root*.

    Args:
        path: The path to validate (absolute or relative).
        workspace_root: The allowed root directory.

    Returns:
        The fully-resolved :class:`~pathlib.Path` if it is safe.

    Raises:
        PathEscapeError: If the resolved path escapes the workspace root.
    """
    root = Path(workspace_root).resolve()

    # Resolve relative paths relative to workspace_root rather than os.getcwd()
    target = Path(path)
    if not target.is_absolute():
        target = root / target

    resolved = target.resolve()

    try:
        resolved.relative_to(root)
    except ValueError:
        raise PathEscapeError(
            f"Path '{resolved}' is outside the workspace root '{root}'."
        ) from None

    return resolved
