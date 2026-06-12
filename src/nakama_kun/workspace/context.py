from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nakama_kun.workspace.analyzer import ProjectAnalysis, WorkspaceAnalyzer
from nakama_kun.workspace.scanner import DirectoryScanner, DirectoryScanResult


class WorkspaceContextBuilder:
    """Orchestrates scanning and analysis to construct a concise Markdown context summary."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.scanner = DirectoryScanner(self.workspace_root)
        self.analyzer = WorkspaceAnalyzer(self.workspace_root)

    def build_summary(self) -> str:
        """Scan, analyze, and format the project context into a Markdown summary."""
        scan_result = self.scanner.scan()
        analysis = self.analyzer.analyze(scan_result)
        summary = self.format_context(scan_result, analysis)
        try:
            from nakama_kun.memory import get_memory_repository
            repo = get_memory_repository()
            repo.save_project_summary(self.workspace_root.name, summary)
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to cache project summary: {e}")
        return summary

    def format_context(self, scan_result: DirectoryScanResult, analysis: ProjectAnalysis) -> str:
        """Render the DirectoryScanResult and ProjectAnalysis as a clean Markdown prompt addition."""
        lines = []
        lines.append("## Workspace Context Summary")
        lines.append(f"- **Project Root**: `{self.workspace_root.name}`")
        lines.append(f"- **Primary Language**: {analysis.primary_language}")

        # Languages breakdown
        if analysis.languages:
            lang_strs = [f"{lang} ({count})" for lang, count in sorted(analysis.languages.items(), key=lambda x: -x[1])]
            lines.append(f"- **Languages Detected**: {', '.join(lang_strs)}")

        # Frameworks
        if analysis.frameworks:
            lines.append(f"- **Frameworks/Tooling**: {', '.join(analysis.frameworks)}")
        else:
            lines.append("- **Frameworks/Tooling**: None detected")

        # Layout & Tests
        lines.append(f"- **Project Layout**: {analysis.layout}")
        if analysis.test_directories:
            lines.append(f"- **Test Directories**: {', '.join(analysis.test_directories)}")
        else:
            lines.append("- **Test Directories**: None found")

        # Dependency configuration files
        if analysis.dependency_files:
            lines.append(f"- **Dependency Files**: {', '.join(analysis.dependency_files)}")

        # Entry points
        if analysis.entry_points:
            lines.append(f"- **Entry Points**: {', '.join(analysis.entry_points)}")

        # Total sizes
        lines.append(f"- **Workspace Size**: {scan_result.total_size_bytes:,} bytes across {len(scan_result.files)} files")

        # Directory structure overview (depth 2 tree visualization)
        lines.append("\n### Project Structure Overview")
        tree_lines = self._generate_structure_tree(scan_result)
        if tree_lines:
            lines.append("```")
            lines.extend(tree_lines)
            lines.append("```")
        else:
            lines.append("No files detected.")

        return "\n".join(lines)

    def _generate_structure_tree(self, scan_result: DirectoryScanResult) -> list[str]:
        """Produce a simplified text-based directory tree representation of the workspace."""
        # Build nested dictionary of paths
        tree: dict[str, Any] = {}

        # Root files to display
        root_files: list[str] = []

        # We'll process all folders first, then files
        for folder in sorted(scan_result.folders):
            parts = Path(folder).parts
            current = tree
            for part in parts[:3]:  # Limit depth to 3 in tree definition
                if part not in current:
                    current[part] = {}
                current = current[part]

        for file_info in sorted(scan_result.files, key=lambda f: f.path):
            parts = Path(file_info.path).parts
            # If it's a root file, save it
            if len(parts) == 1:
                root_files.append(file_info.name)
            else:
                # Add file under its folder in the tree
                current = tree
                for part in parts[:-1][:3]:  # Traverse folder structure up to depth 3
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                # We store files as leaf nodes mapping to None
                # Check that we haven't reached depth limit
                if len(parts) <= 3:
                    current[parts[-1]] = None

        # Build output lines recursively
        output: list[str] = []

        def recurse(node: dict[str, Any] | None, prefix: str) -> None:
            if node is None:
                return
            keys = sorted(node.keys())
            for i, key in enumerate(keys):
                is_last = (i == len(keys) - 1)
                connector = "└── " if is_last else "├── "
                val = node[key]
                if val is None:
                    # File
                    output.append(f"{prefix}{connector}{key}")
                else:
                    # Folder
                    output.append(f"{prefix}{connector}{key}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    recurse(val, new_prefix)

        # Draw root level folders/files
        recurse(tree, "")

        # Draw any root level files that weren't inside folders or printed
        for file_name in root_files:
            # If we already have lines, check if it's the last element overall
            # Actually, to make formatting simple, just print them as root level elements
            output.append(f"├── {file_name}")

        # Let's clean up tree lines: ensure no duplicate lines or files printed twice
        unique_lines = []
        seen = set()
        for line in output:
            if line not in seen:
                unique_lines.append(line)
                seen.add(line)

        # Cap the output length at 40 lines to keep prompt short and clean
        if len(unique_lines) > 40:
            truncated = unique_lines[:40]
            truncated.append("... (some directories/files truncated)")
            return truncated

        return unique_lines
