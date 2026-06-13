from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nakama_kun.workspace.models import ProjectSnapshot, GitInfo, TestInfo as WorkspaceTestInfo
from nakama_kun.workspace.scanner_service import WorkspaceScanner
from nakama_kun.workspace.summary_builder import WorkspaceSummaryBuilder
from nakama_kun.workspace.context import WorkspaceContextBuilder


def test_workspace_scanner_scans_and_writes_cache(tmp_path: Path) -> None:
    # 1. Setup a mocked structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "src" / "cli.py").write_text("# cli entry")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test(): pass")
    (tmp_path / "requirements.txt").write_text("rich>=10.0\npytest\n")

    # 2. Perform scan
    scanner = WorkspaceScanner(workspace_root=tmp_path)
    # Mock GitInfo to avoid calling actual git commands
    with patch.object(scanner, "_get_git_info", return_value=GitInfo(branch="main", commit_hash="abcdef123", status_clean=True)):
        snapshot = scanner.scan()

    # 3. Assertions
    assert "src/main.py" in snapshot.files
    assert "src/cli.py" in snapshot.files
    assert "tests/test_main.py" in snapshot.files
    assert "src/main.py" in snapshot.entrypoints
    assert "src/cli.py" in snapshot.entrypoints
    assert "tests" in snapshot.tests.directories
    assert "tests/test_main.py" in snapshot.tests.files
    assert "rich" in snapshot.dependencies
    assert "pytest" in snapshot.dependencies
    assert snapshot.git_info.branch == "main"
    assert snapshot.git_info.commit_hash == "abcdef123"

    # Verify snapshot cache file exists
    cache_file = tmp_path / ".workspace" / "workspace_snapshot.json"
    assert cache_file.exists()
    
    # Check that cache has correct schema
    with open(cache_file, encoding="utf-8") as f:
        data = json.load(f)
        assert data["git_info"]["branch"] == "main"
        assert len(data["files"]) > 0


def test_workspace_scanner_dependency_parsing(tmp_path: Path) -> None:
    # 1. pyproject.toml poetry-style and project dependencies
    pyproject_content = """
[project]
name = "test-proj"
dependencies = [
    "fastapi>=0.95.0",
]
[dependency-groups]
dev = [
    "black",
]
[tool.poetry.dependencies]
requests = "^2.28.0"
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content)

    # 2. package.json dependencies
    package_json = {
        "dependencies": {
            "lodash": "^4.17.21"
        },
        "devDependencies": {
            "typescript": "^5.0.0"
        }
    }
    (tmp_path / "package.json").write_text(json.dumps(package_json))

    scanner = WorkspaceScanner(workspace_root=tmp_path)
    deps = scanner._extract_dependencies()

    assert "fastapi" in deps
    assert "black" in deps
    assert "requests" in deps
    assert "lodash" in deps
    assert "typescript" in deps


def test_workspace_summary_builder() -> None:
    snapshot = ProjectSnapshot(
        files=["src/main.py", "app.py", "tests/test_main.py", "package.json"],
        folders=["src", "tests"],
        languages={"Python": 3, "JSON": 1},
        dependencies=["fastapi", "pytest"],
        entrypoints=["src/main.py", "app.py"],
        tests=WorkspaceTestInfo(directories=["tests"], files=["tests/test_main.py"]),
        git_info=GitInfo(branch="dev", commit_hash="1234567890", status_clean=False),
    )

    summary = WorkspaceSummaryBuilder.build_summary(snapshot)

    assert "Python Project" in summary or "JavaScript Project" in summary
    assert "Python (3 files, 75.0%)" in summary
    assert "fastapi, pytest" in summary
    assert "src/main.py, app.py" in summary
    assert "Directories: tests | Files: 1 test files found" in summary
    assert "Branch `dev`" in summary
    assert "Commit `1234567`" in summary


def test_workspace_context_builder_uses_cache(tmp_path: Path) -> None:
    # 1. Write pre-defined snapshot file
    cache_dir = tmp_path / ".workspace"
    cache_dir.mkdir()
    
    predefined_snapshot = ProjectSnapshot(
        files=["src/main.py"],
        folders=["src"],
        languages={"Python": 1},
        dependencies=["pytest"],
        entrypoints=["src/main.py"],
        tests=WorkspaceTestInfo(directories=[], files=[]),
        git_info=GitInfo(branch="master", commit_hash="999999", status_clean=True)
    )
    
    with open(cache_dir / "workspace_snapshot.json", "w", encoding="utf-8") as f:
        f.write(predefined_snapshot.model_dump_json(indent=2))

    # 2. Use context builder
    builder = WorkspaceContextBuilder(workspace_root=tmp_path)
    
    # We patch scanner to verify that `WorkspaceScanner.scan` is NOT called when cache exists
    with patch("nakama_kun.workspace.scanner_service.WorkspaceScanner.scan") as mock_scan:
        summary = builder.build_summary()
        mock_scan.assert_not_called()

    # Verify that the generated summary matches our pre-defined cache values
    assert "pytest" in summary
    assert "master" in summary
    assert "999999" in summary
