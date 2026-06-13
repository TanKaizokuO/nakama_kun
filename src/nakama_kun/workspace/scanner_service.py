from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from nakama_kun.workspace.scanner import DirectoryScanner
from nakama_kun.workspace.analyzer import WorkspaceAnalyzer
from nakama_kun.workspace.models import ProjectSnapshot, GitInfo, TestInfo


class WorkspaceScanner:
    """Service that scans a workspace to generate a detailed ProjectSnapshot."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.scanner = DirectoryScanner(self.workspace_root)

    def scan(self) -> ProjectSnapshot:
        """Scan the repository and construct a ProjectSnapshot, saving it to disk."""
        scan_result = self.scanner.scan()

        # 1. Gather files and folders
        files = [f.path for f in scan_result.files]
        folders = scan_result.folders

        # 2. Collect languages counts
        languages: dict[str, int] = {}
        for ext, count in scan_result.extensions.items():
            lang = WorkspaceAnalyzer.EXTENSION_MAP.get(ext)
            if lang:
                languages[lang] = languages.get(lang, 0) + count

        # 3. Discovers common entrypoints
        # The requirements specify discovering common entrypoints: main.py, app.py, manage.py, cli.py
        common_entrypoint_names = {"main.py", "app.py", "manage.py", "cli.py"}
        entrypoints: list[str] = []
        for file_info in scan_result.files:
            # Match files in the root or direct subdirectories (e.g. src/main.py, src/nakama_kun/main.py)
            p = Path(file_info.path)
            if p.name in common_entrypoint_names:
                # Limit to root or top-level / direct subfolders to avoid deep nested unrelated files
                if len(p.parts) <= 3:
                    entrypoints.append(file_info.path)

        # 4. Discovers test directories and test files
        test_dir_names = {"tests", "test", "__tests__", "spec"}
        test_dirs: list[str] = []
        # Find top level folders matching test directory names
        for folder in folders:
            parts = Path(folder).parts
            if parts and parts[0].lower() in test_dir_names:
                if parts[0] not in test_dirs:
                    test_dirs.append(parts[0])

        test_files: list[str] = []
        for file_info in scan_result.files:
            p = Path(file_info.path)
            is_in_test_dir = any(part.lower() in test_dir_names for part in p.parts)
            is_test_pattern = (
                p.name.startswith("test_")
                or (p.stem.endswith("_test") and p.suffix in {".py", ".js", ".ts", ".go", ".rs"})
            )
            if is_in_test_dir or is_test_pattern:
                test_files.append(file_info.path)

        # Sort entrypoints and tests for predictability
        entrypoints.sort()
        test_dirs.sort()
        test_files.sort()

        # 5. Extract dependencies from pyproject.toml, requirements.txt, package.json
        dependencies = self._extract_dependencies()

        # 6. Extract git_info
        git_info = self._get_git_info()

        # 7. Construct ProjectSnapshot
        snapshot = ProjectSnapshot(
            files=files,
            folders=folders,
            languages=languages,
            dependencies=dependencies,
            entrypoints=entrypoints,
            tests=TestInfo(directories=test_dirs, files=test_files),
            git_info=git_info,
            generated_at=datetime.now(UTC),
        )

        # 8. Save snapshot to .workspace/workspace_snapshot.json
        self._save_snapshot(snapshot)

        return snapshot

    def _extract_dependencies(self) -> list[str]:
        """Extract dependency names from package definitions."""
        dependencies: set[str] = set()

        # pyproject.toml
        pyproject_path = self.workspace_root / "pyproject.toml"
        if pyproject_path.exists():
            try:
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                
                # Check [project] dependencies
                project_data = data.get("project", {})
                deps = project_data.get("dependencies", [])
                if isinstance(deps, list):
                    for dep in deps:
                        name = self._clean_dependency_name(dep)
                        if name:
                            dependencies.add(name)

                # Check dev dependencies / dependency groups
                dev_deps = data.get("dependency-groups", {}).get("dev", [])
                if isinstance(dev_deps, list):
                    for dep in dev_deps:
                        name = self._clean_dependency_name(dep)
                        if name:
                            dependencies.add(name)

                # Check tool.poetry.dependencies
                poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                if isinstance(poetry_deps, dict):
                    for dep_name in poetry_deps:
                        if dep_name.lower() != "python":
                            dependencies.add(dep_name)
            except Exception:
                pass

        # package.json
        package_json_path = self.workspace_root / "package.json"
        if package_json_path.exists():
            try:
                with open(package_json_path, encoding="utf-8") as f:
                    data = json.load(f)
                
                for dep_key in ("dependencies", "devDependencies"):
                    deps = data.get(dep_key, {})
                    if isinstance(deps, dict):
                        for dep_name in deps:
                            dependencies.add(dep_name)
            except Exception:
                pass

        # requirements.txt
        requirements_path = self.workspace_root / "requirements.txt"
        if requirements_path.exists():
            try:
                with open(requirements_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith(("#", "-r", "-c", "--")):
                            continue
                        name = self._clean_dependency_name(line)
                        if name:
                            dependencies.add(name)
            except Exception:
                pass

        return sorted(list(dependencies))

    def _clean_dependency_name(self, raw_dep: str) -> str:
        """Strip versions and markers from a raw dependency spec."""
        name = raw_dep.strip()
        for char in ("==", ">=", "<=", ">", "<", "~=", ";", "#", "@", "["):
            name = name.split(char)[0]
        return name.strip()

    def _get_git_info(self) -> GitInfo:
        """Safely fetch git info via subprocess commands."""
        info = GitInfo(branch=None, commit_hash=None, committed_at=None, status_clean=True)

        if not shutil.which("git"):
            return info

        try:
            # Verify if it's a git repo
            res = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                check=True,
            )
            if "true" not in res.stdout.lower():
                return info
        except Exception:
            return info

        # Extract branch name
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                check=True,
            )
            info.branch = res.stdout.strip()
        except Exception:
            pass

        # Extract commit hash
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                check=True,
            )
            info.commit_hash = res.stdout.strip()
        except Exception:
            pass

        # Extract committed timestamp
        try:
            res = subprocess.run(
                ["git", "log", "-1", "--format=%cI"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                check=True,
            )
            info.committed_at = res.stdout.strip()
        except Exception:
            pass

        # Extract clean status
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                check=True,
            )
            info.status_clean = len(res.stdout.strip()) == 0
        except Exception:
            pass

        return info

    def _save_snapshot(self, snapshot: ProjectSnapshot) -> None:
        """Write the ProjectSnapshot object to the local filesystem."""
        snapshot_dir = self.workspace_root / ".workspace"
        try:
            snapshot_dir.mkdir(exist_ok=True)
            snapshot_path = snapshot_dir / "workspace_snapshot.json"
            # Serialize using Pydantic
            with open(snapshot_path, "w", encoding="utf-8") as f:
                f.write(snapshot.model_dump_json(indent=2))
        except Exception:
            pass
