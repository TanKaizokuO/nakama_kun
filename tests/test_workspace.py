from __future__ import annotations

import json
from pathlib import Path

from nakama_kun.workspace.analyzer import WorkspaceAnalyzer
from nakama_kun.workspace.context import WorkspaceContextBuilder
from nakama_kun.workspace.scanner import DirectoryScanner


def test_directory_scanner_ignores_and_bounds(tmp_path: Path) -> None:
    # 1. Create a mocked project layout
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "src" / "utils.py").write_text("# utils")
    
    # Ignored directory
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]")
    
    # Sub-folder
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test(): pass")

    # 2. Perform scan
    scanner = DirectoryScanner(workspace_root=tmp_path)
    result = scanner.scan()

    # 3. Assertions
    # We should see src/main.py, src/utils.py, tests/test_main.py, but NOT .git/config
    scanned_files = {f.path for f in result.files}
    assert "src/main.py" in scanned_files
    assert "src/utils.py" in scanned_files
    assert "tests/test_main.py" in scanned_files
    assert ".git/config" not in scanned_files

    assert "src" in result.folders
    assert "tests" in result.folders
    assert ".git" not in result.folders

    assert result.extensions.get(".py") == 3
    assert result.total_size_bytes > 0


def test_directory_scanner_max_files(tmp_path: Path) -> None:
    # Create 5 files
    for i in range(5):
        (tmp_path / f"file_{i}.py").write_text("# dummy")

    # Scan with max_files = 2
    scanner = DirectoryScanner(workspace_root=tmp_path, max_files=2)
    result = scanner.scan()

    assert len(result.files) == 2


def test_workspace_analyzer_python_pyproject(tmp_path: Path) -> None:
    # Create pyproject.toml
    pyproject_content = """
[project]
name = "test-project"
dependencies = [
    "fastapi>=0.100.0",
    "typer",
]

[project.scripts]
run-app = "test_project.main:main"

[tool.poetry.dependencies]
pytest = "^7.0.0"
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# entry point")
    (tmp_path / "src" / "utils.py").write_text("# utils")
    (tmp_path / "tests").mkdir()

    scanner = DirectoryScanner(workspace_root=tmp_path)
    scan_result = scanner.scan()

    analyzer = WorkspaceAnalyzer(workspace_root=tmp_path)
    analysis = analyzer.analyze(scan_result)

    assert analysis.primary_language == "Python"
    assert "pyproject.toml" in analysis.dependency_files
    assert "tests" in analysis.test_directories
    assert analysis.layout == "src-layout"
    
    # Check framework detections
    assert "FastAPI" in analysis.frameworks
    assert "Typer CLI" in analysis.frameworks

    # Entry points
    assert any("run-app" in ep for ep in analysis.entry_points)
    assert any("src/main.py" in ep for ep in analysis.entry_points)


def test_workspace_analyzer_node_project(tmp_path: Path) -> None:
    # Create package.json
    package_json = {
        "name": "node-project",
        "main": "dist/index.js",
        "dependencies": {
            "react": "^18.2.0",
            "next": "^14.0.0"
        },
        "devDependencies": {
            "typescript": "^5.0.0"
        }
    }
    (tmp_path / "package.json").write_text(json.dumps(package_json))
    (tmp_path / "index.js").write_text("// entry")
    (tmp_path / "next.config.js").write_text("// next config")

    scanner = DirectoryScanner(workspace_root=tmp_path)
    scan_result = scanner.scan()

    analyzer = WorkspaceAnalyzer(workspace_root=tmp_path)
    analysis = analyzer.analyze(scan_result)

    assert analysis.primary_language == "JavaScript"
    assert "package.json" in analysis.dependency_files
    assert "React" in analysis.frameworks
    assert "Next.js" in analysis.frameworks
    assert "TypeScript Compiler" in analysis.frameworks
    assert any("index.js" in ep for ep in analysis.entry_points)


def test_workspace_context_builder(tmp_path: Path) -> None:
    # Create pyproject.toml
    pyproject_content = """
[project]
name = "test-project"
dependencies = ["typer"]
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.py").write_text("# lib")
    (tmp_path / "src" / "main.py").write_text("# main")

    builder = WorkspaceContextBuilder(workspace_root=tmp_path)
    summary = builder.build_summary()

    assert "Workspace Context Summary" in summary
    assert "test-project" in summary or tmp_path.name in summary
    assert "Python" in summary
    assert "src/lib.py" in summary or "src/" in summary


def test_find_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest
    from nakama_kun.config import find_env_file

    # Create dummy .env in temp path
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_VAR=1")

    # Create a sub-folder to simulate running from tests/
    sub_dir = tmp_path / "tests" / "sub"
    sub_dir.mkdir(parents=True)

    # Monkeypatch CWD to the sub-folder
    monkeypatch.chdir(sub_dir)

    resolved = find_env_file()
    assert Path(resolved).resolve() == env_file.resolve()

