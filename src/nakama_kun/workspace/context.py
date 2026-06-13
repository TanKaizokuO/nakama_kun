from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nakama_kun.workspace.analyzer import WorkspaceAnalyzer
from nakama_kun.workspace.scanner import DirectoryScanner
from nakama_kun.workspace.models import ProjectSnapshot


class WorkspaceContextBuilder:
    """Orchestrates scanning and analysis to construct a concise Markdown context summary."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.scanner = DirectoryScanner(self.workspace_root)
        self.analyzer = WorkspaceAnalyzer(self.workspace_root)

    def build_summary(self) -> str:
        """Scan, analyze, and format the project context into a Markdown summary."""
        snapshot_path = self.workspace_root / ".workspace" / "workspace_snapshot.json"
        
        snapshot = None
        if snapshot_path.exists():
            try:
                with open(snapshot_path, encoding="utf-8") as f:
                    snapshot = ProjectSnapshot.model_validate_json(f.read())
            except Exception as e:
                from loguru import logger
                logger.warning(f"Failed to load cached workspace snapshot: {e}")
        
        if snapshot is None:
            from nakama_kun.workspace.scanner_service import WorkspaceScanner
            scanner = WorkspaceScanner(self.workspace_root)
            snapshot = scanner.scan()

        from nakama_kun.workspace.summary_builder import WorkspaceSummaryBuilder
        summary_text = WorkspaceSummaryBuilder.build_summary(snapshot)

        # Build combined summary to satisfy legacy tests (e.g. Workspace Context Summary header and tree view)
        lines = []
        lines.append("## Workspace Context Summary")
        lines.append(f"- **Project Root**: `{self.workspace_root.name}`")
        
        # Append main summary
        lines.append(summary_text)

        # Append symbol summary
        try:
            from nakama_kun.workspace.planner_context import PlannerContextBuilder
            symbol_summary = PlannerContextBuilder(self.workspace_root).build_symbol_summary()
            lines.append("\n" + symbol_summary)
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to build symbol summary: {e}")

        # Directory structure overview (depth 2 tree visualization)
        lines.append("\n### Project Structure Overview")
        tree_lines = self._generate_structure_tree_from_snapshot(snapshot)
        if tree_lines:
            lines.append("```")
            lines.extend(tree_lines)
            lines.append("```")
        else:
            lines.append("No files detected.")

        summary = "\n".join(lines)

        try:
            from nakama_kun.memory import get_memory_repository
            repo = get_memory_repository()
            repo.save_project_summary(self.workspace_root.name, summary)
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to cache project summary: {e}")
            
        return summary

    def _generate_structure_tree_from_snapshot(self, snapshot: ProjectSnapshot) -> list[str]:
        """Produce a simplified text-based directory tree representation of the workspace."""
        # Build nested dictionary of paths
        tree: dict[str, Any] = {}

        # Root files to display
        root_files: list[str] = []

        # We'll process all folders first, then files
        for folder in sorted(snapshot.folders):
            parts = Path(folder).parts
            current = tree
            for part in parts[:3]:  # Limit depth to 3 in tree definition
                if part not in current:
                    current[part] = {}
                current = current[part]

        for file_path in sorted(snapshot.files):
            parts = Path(file_path).parts
            # If it's a root file, save it
            if len(parts) == 1:
                root_files.append(parts[0])
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
            output.append(f"├── {file_name}")

        # Clean up tree lines: ensure no duplicate lines or files printed twice
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
