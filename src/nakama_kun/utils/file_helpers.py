"""Utility functions for file operations used across the project."""

import os
from pathlib import Path
from typing import List, Optional


def get_home_dir() -> Optional[Path]:
    """Return the user's home directory, or None if unavailable."""
    home = Path.home()
    if home.exists():
        return home
    # Fallback to environment variable
    home_str = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if home_str:
        return Path(home_str)
    return None


def get_video_extensions() -> List[str]:
    """Return a list of common video file extensions (lowercase, with dot)."""
    return [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".3gp", ".ogv"]


def format_size(size_bytes: int) -> str:
    """Convert bytes to human-readable format (e.g., 1.23 MB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"
