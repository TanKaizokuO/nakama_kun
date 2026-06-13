from __future__ import annotations

from datetime import datetime, UTC
from pydantic import BaseModel, Field


class GitInfo(BaseModel):
    """Git repository metadata."""

    branch: str | None = Field(default=None, description="Current branch name.")
    commit_hash: str | None = Field(default=None, description="Latest commit hash.")
    committed_at: str | None = Field(default=None, description="Commit timestamp.")
    status_clean: bool = Field(default=True, description="True if workspace is clean.")


class TestInfo(BaseModel):
    """Workspace test details."""

    directories: list[str] = Field(default_factory=list, description="Top-level test directories.")
    files: list[str] = Field(default_factory=list, description="Relative paths of test files.")


class ProjectSnapshot(BaseModel):
    """Overall cached snapshot of the workspace."""

    files: list[str] = Field(default_factory=list, description="Relative file paths.")
    folders: list[str] = Field(default_factory=list, description="Relative folder paths.")
    languages: dict[str, int] = Field(default_factory=dict, description="Detected language file counts.")
    dependencies: list[str] = Field(default_factory=list, description="Extracted project dependencies.")
    entrypoints: list[str] = Field(default_factory=list, description="Detected entrypoint files.")
    tests: TestInfo = Field(default_factory=TestInfo, description="Detected test directories and files.")
    git_info: GitInfo = Field(default_factory=GitInfo, description="Git metadata.")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Generation timestamp.")


class Symbol(BaseModel):
    """Represents a code symbol (class, function, method, or import) in the workspace."""

    name: str = Field(description="Name of the symbol.")
    type: str = Field(description="Type of symbol: 'class', 'function', 'method', 'import'.")
    file: str = Field(description="Relative file path where the symbol is defined.")
    line: int = Field(description="Line number where the symbol definition starts (1-indexed).")
    parent: str | None = Field(default=None, description="Name of the parent class or function, if nested.")
    decorators: list[str] = Field(default_factory=list, description="List of decorators applied to the symbol.")
