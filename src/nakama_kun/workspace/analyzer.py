from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nakama_kun.workspace.scanner import DirectoryScanResult


@dataclass
class ProjectAnalysis:
    """Detailed structural analysis of a workspace."""
    primary_language: str = "Unknown"
    languages: dict[str, int] = field(default_factory=dict)  # lang_name -> file_count
    frameworks: list[str] = field(default_factory=list)
    dependency_files: list[str] = field(default_factory=list)  # rel paths of found dep files
    entry_points: list[str] = field(default_factory=list)
    test_directories: list[str] = field(default_factory=list)
    layout: str = "flat"  # flat, src-layout, or monorepo
    dependencies: list[str] = field(default_factory=list)  # Direct external deps detected


class WorkspaceAnalyzer:
    """Analyzes a scanned workspace directory to detect frameworks, languages, entry points, etc."""

    # File extensions mapped to programming languages
    EXTENSION_MAP: dict[str, str] = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".rs": "Rust",
        ".go": "Go",
        ".java": "Java",
        ".kt": "Kotlin",
        ".kts": "Kotlin",
        ".swift": "Swift",
        ".rb": "Ruby",
        ".php": "PHP",
        ".cs": "C#",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".c": "C",
        ".h": "C/C++ Header",
        ".hpp": "C/C++ Header",
        ".sh": "Shell",
        ".bash": "Shell",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".json": "JSON",
        ".toml": "TOML",
        ".md": "Markdown",
        ".html": "HTML",
        ".css": "CSS",
    }

    # Dependency filenames to search for
    DEP_FILENAMES: set[str] = {
        "pyproject.toml",
        "requirements.txt",
        "Pipfile",
        "poetry.lock",
        "setup.py",
        "uv.lock",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.toml",
        "Cargo.lock",
        "go.mod",
        "go.sum",
        "Gemfile",
        "Gemfile.lock",
        "composer.json",
        "pom.xml",
        "build.gradle",
    }

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()

    def analyze(self, scan_result: DirectoryScanResult) -> ProjectAnalysis:
        """Run heuristics on scan results and configuration files to determine project properties."""
        analysis = ProjectAnalysis()

        # 1. Detect Languages by File Extensions
        self._detect_languages(scan_result, analysis)

        # 2. Detect Dependency Files
        self._detect_dependency_files(scan_result, analysis)

        # 3. Detect Test Directories
        self._detect_test_directories(scan_result, analysis)

        # 4. Detect Layout
        self._detect_layout(scan_result, analysis)

        # 5. Safe parsing of configurations for framework and entry point detection
        self._parse_config_files(analysis)

        # 6. Fallback Entry Point checks based on common files
        self._find_fallback_entry_points(scan_result, analysis)

        return analysis

    def _detect_languages(self, scan_result: DirectoryScanResult, analysis: ProjectAnalysis) -> None:
        """Counts files by language and sets the primary language."""
        lang_counts: dict[str, int] = {}
        for ext, count in scan_result.extensions.items():
            lang = self.EXTENSION_MAP.get(ext)
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + count

        analysis.languages = lang_counts
        if lang_counts:
            # Primary language is the one with the most files
            analysis.primary_language = max(lang_counts, key=lang_counts.get)  # type: ignore

    def _detect_dependency_files(self, scan_result: DirectoryScanResult, analysis: ProjectAnalysis) -> None:
        """Identifies any files that function as dependency definitions."""
        found_deps = []
        for file_info in scan_result.files:
            if file_info.name in self.DEP_FILENAMES:
                found_deps.append(file_info.path)
        # Sort so root-level or predictable files come first
        analysis.dependency_files = sorted(found_deps, key=lambda p: (p.count("/"), p))

    def _detect_test_directories(self, scan_result: DirectoryScanResult, analysis: ProjectAnalysis) -> None:
        """Locates standard test folders."""
        test_dir_names = {"tests", "test", "__tests__", "spec"}
        found_test_dirs = []
        for folder in scan_result.folders:
            parts = Path(folder).parts
            if parts and parts[0].lower() in test_dir_names:
                # Add only top-level test folder if possible
                top_test = parts[0]
                if top_test not in found_test_dirs:
                    found_test_dirs.append(top_test)

        # If we didn't find top level test folders from the folder scan but "tests" folder exists in root, use it
        for folder_name in test_dir_names:
            if (self.workspace_root / folder_name).is_dir() and folder_name not in found_test_dirs:
                found_test_dirs.append(folder_name)

        analysis.test_directories = found_test_dirs

    def _detect_layout(self, scan_result: DirectoryScanResult, analysis: ProjectAnalysis) -> None:
        """Infers package structure (monorepo, src-layout, flat)."""
        folders_set = {Path(f).parts[0] for f in scan_result.folders if f}

        if "packages" in folders_set or "apps" in folders_set:
            analysis.layout = "monorepo"
        elif "src" in folders_set:
            analysis.layout = "src-layout"
        else:
            analysis.layout = "flat"

    def _parse_config_files(self, analysis: ProjectAnalysis) -> None:
        """Tries to read pyproject.toml, package.json, and Cargo.toml for frameworks, entry points, deps."""
        # Check pyproject.toml
        pyproject_path = self.workspace_root / "pyproject.toml"
        if pyproject_path.exists():
            try:
                with open(pyproject_path, "rb") as f:
                    data = tomllib.load(f)
                self._parse_pyproject(data, analysis)
            except Exception:  # Safe parse, ignore exceptions
                pass

        # Check package.json
        package_json_path = self.workspace_root / "package.json"
        if package_json_path.exists():
            try:
                with open(package_json_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._parse_package_json(data, analysis)
            except Exception:  # Safe parse, ignore exceptions
                pass

        # Check Cargo.toml
        cargo_toml_path = self.workspace_root / "Cargo.toml"
        if cargo_toml_path.exists():
            try:
                with open(cargo_toml_path, "rb") as f:
                    data = tomllib.load(f)
                self._parse_cargo_toml(data, analysis)
            except Exception:  # Safe parse, ignore exceptions
                pass

    def _parse_pyproject(self, data: dict[str, Any], analysis: ProjectAnalysis) -> None:
        """Parses pyproject.toml contents."""
        # 1. Direct dependencies
        project_data = data.get("project", {})
        deps = project_data.get("dependencies", [])
        if isinstance(deps, list):
            for dep in deps:
                # Strip versions to clean names (e.g. "typer>=0.12.3" -> "typer")
                dep_name = dep.split(">")[0].split("=")[0].split("<")[0].split("~")[0].strip()
                if dep_name not in analysis.dependencies:
                    analysis.dependencies.append(dep_name)

        # Dev / Dependency-groups
        dev_deps = data.get("dependency-groups", {}).get("dev", [])
        if isinstance(dev_deps, list):
            for dep in dev_deps:
                dep_name = dep.split(">")[0].split("=")[0].split("<")[0].split("~")[0].strip()
                if dep_name not in analysis.dependencies:
                    analysis.dependencies.append(dep_name)

        # Poetry-specific dependencies
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        if isinstance(poetry_deps, dict):
            for dep_name in poetry_deps:
                if dep_name != "python" and dep_name not in analysis.dependencies:
                    analysis.dependencies.append(dep_name)

        # 2. Heuristic framework detection
        framework_keywords = {
            "fastapi": "FastAPI",
            "django": "Django",
            "flask": "Flask",
            "streamlit": "Streamlit",
            "typer": "Typer CLI",
            "click": "Click CLI",
            "pytest": "Pytest",
            "ruff": "Ruff",
            "mypy": "Mypy",
        }
        for kw, frame_name in framework_keywords.items():
            if any(kw in dep.lower() for dep in analysis.dependencies) and frame_name not in analysis.frameworks:
                analysis.frameworks.append(frame_name)

        # 3. Entry points
        scripts = project_data.get("scripts", {})
        if isinstance(scripts, dict):
            for name, path in scripts.items():
                analysis.entry_points.append(f"CLI script: {name} ({path})")

        poetry_scripts = data.get("tool", {}).get("poetry", {}).get("scripts", {})
        if isinstance(poetry_scripts, dict):
            for name, path in poetry_scripts.items():
                entry = f"Poetry script: {name} ({path})"
                if entry not in analysis.entry_points:
                    analysis.entry_points.append(entry)

    def _parse_package_json(self, data: dict[str, Any], analysis: ProjectAnalysis) -> None:
        """Parses package.json contents."""
        # 1. Direct dependencies
        deps = data.get("dependencies", {})
        dev_deps = data.get("devDependencies", {})

        all_deps = list(deps.keys()) + list(dev_deps.keys())
        for dep in all_deps:
            if dep not in analysis.dependencies:
                analysis.dependencies.append(dep)

        # 2. Heuristic framework detection
        framework_keywords = {
            "react": "React",
            "vue": "Vue",
            "next": "Next.js",
            "express": "Express",
            "svelte": "Svelte",
            "angular": "Angular",
            "vite": "Vite",
            "nuxt": "Nuxt.js",
            "gatsby": "Gatsby",
            "tailwindcss": "TailwindCSS",
            "typescript": "TypeScript Compiler",
        }
        for kw, frame_name in framework_keywords.items():
            if kw in all_deps and frame_name not in analysis.frameworks:
                analysis.frameworks.append(frame_name)

        # Framework-specific files check too
        for file_chk, frame_name in [
            ("next.config.js", "Next.js"),
            ("next.config.ts", "Next.js"),
            ("svelte.config.js", "Svelte"),
            ("vite.config.js", "Vite"),
            ("vite.config.ts", "Vite"),
            ("tailwind.config.js", "TailwindCSS"),
        ]:
            if (self.workspace_root / file_chk).exists() and frame_name not in analysis.frameworks:
                analysis.frameworks.append(frame_name)

        # 3. Entry points
        if "main" in data:
            analysis.entry_points.append(f"package.json main: {data['main']}")
        if "bin" in data:
            bins = data["bin"]
            if isinstance(bins, str):
                analysis.entry_points.append(f"package.json bin: {bins}")
            elif isinstance(bins, dict):
                for name, path in bins.items():
                    analysis.entry_points.append(f"package.json bin script: {name} ({path})")

    def _parse_cargo_toml(self, data: dict[str, Any], analysis: ProjectAnalysis) -> None:
        """Parses Cargo.toml contents."""
        deps = data.get("dependencies", {})
        if isinstance(deps, dict):
            for dep_name in deps:
                if dep_name not in analysis.dependencies:
                    analysis.dependencies.append(dep_name)

        framework_keywords = {
            "tokio": "Tokio (Async)",
            "actix-web": "Actix-Web",
            "axum": "Axum",
            "rocket": "Rocket",
            "serde": "Serde Serialization",
        }
        for kw, frame_name in framework_keywords.items():
            if kw in deps and frame_name not in analysis.frameworks:
                analysis.frameworks.append(frame_name)

        # Check binary outputs
        bin_list = data.get("bin", [])
        if isinstance(bin_list, list):
            for b in bin_list:
                if isinstance(b, dict) and "name" in b:
                    analysis.entry_points.append(f"Cargo binary: {b['name']}")

    def _find_fallback_entry_points(self, scan_result: DirectoryScanResult, analysis: ProjectAnalysis) -> None:
        """Scans the file list for common main entry point scripts."""
        common_entry_files = {
            "main.py",
            "app.py",
            "run.py",
            "index.js",
            "index.ts",
            "app.js",
            "app.ts",
            "server.js",
            "main.go",
        }

        # Look in the root and in direct subdirectories (e.g. src/)
        for file_info in scan_result.files:
            p = Path(file_info.path)
            # Root files
            if len(p.parts) == 1 and file_info.name in common_entry_files or len(p.parts) == 2 and p.parts[0] == "src" and file_info.name in common_entry_files or len(p.parts) == 3 and p.parts[0] == "src" and file_info.name in {"main.py", "app.py"}:
                entry = f"Common file: {file_info.path}"
                if entry not in analysis.entry_points:
                    analysis.entry_points.append(entry)
            # Rust standard main
            elif file_info.path == "src/main.rs":
                entry = "Rust binary root: src/main.rs"
                if entry not in analysis.entry_points:
                    analysis.entry_points.append(entry)
            elif file_info.path == "src/lib.rs":
                entry = "Rust library root: src/lib.rs"
                if entry not in analysis.entry_points:
                    analysis.entry_points.append(entry)
