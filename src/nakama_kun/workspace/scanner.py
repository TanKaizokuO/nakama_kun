from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class FileInfo:
    """Represents metadata about a file in the workspace."""
    path: str  # relative to workspace root
    name: str
    extension: str
    size_bytes: int
    modified_time: datetime


@dataclass
class DirectoryScanResult:
    """Contains results of a workspace directory scan."""
    files: list[FileInfo] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)  # relative path
    extensions: dict[str, int] = field(default_factory=dict)  # ext -> count
    total_size_bytes: int = 0
    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DirectoryScanner:
    """Traverses a workspace directory to collect metadata, ignoring specified directories."""

    DEFAULT_IGNORED_DIRS: set[str] = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
        "target",
        "out",
    }

    def __init__(
        self,
        workspace_root: str | Path | None = None,
        ignored_dirs: set[str] | list[str] | None = None,
        max_files: int = 5000,
    ) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        if ignored_dirs is not None:
            self.ignored_dirs = set(ignored_dirs)
        else:
            self.ignored_dirs = self.DEFAULT_IGNORED_DIRS
        self.max_files = max_files

    def scan(self) -> DirectoryScanResult:
        """Scan the workspace and return gathered directory details.

        Only files and folders not within the ignored directory set are collected.
        Traversal is bounded to self.max_files to prevent freezing on huge codebases.
        """
        result = DirectoryScanResult()

        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            return result

        # We keep track of file counts to enforce the boundary
        file_count = 0

        # We'll use os.walk but modify dirs in-place to prune ignored directories
        for root, dirs, files in os.walk(self.workspace_root):
            # Prune ignored directories in-place so os.walk doesn't descend into them
            dirs[:] = [d for d in dirs if d not in self.ignored_dirs]

            # Collect folder paths relative to the workspace root
            root_path = Path(root)
            for d in dirs:
                rel_dir = root_path.joinpath(d).relative_to(self.workspace_root)
                result.folders.append(str(rel_dir))

            # Process files
            for file_name in files:
                if file_count >= self.max_files:
                    # Halt traversal if bounded limit reached
                    break

                file_path = root_path.joinpath(file_name)
                try:
                    stat = file_path.stat()
                except OSError:
                    # Skip files that can't be stat-ed (e.g. broken symlinks, permission issues)
                    continue

                rel_file_path = file_path.relative_to(self.workspace_root)
                ext = file_path.suffix.lower()

                file_info = FileInfo(
                    path=str(rel_file_path),
                    name=file_name,
                    extension=ext,
                    size_bytes=stat.st_size,
                    modified_time=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )

                result.files.append(file_info)
                result.total_size_bytes += stat.st_size
                result.extensions[ext] = result.extensions.get(ext, 0) + 1
                file_count += 1

            if file_count >= self.max_files:
                break

        return result
