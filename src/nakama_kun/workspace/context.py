from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nakama_kun.workspace.analyzer import ProjectAnalysis, WorkspaceAnalyzer
from nakama_kun.workspace.scanner import DirectoryScanner
from nakama_kun.workspace.models import ProjectSnapshot


class WorkspaceContextBuilder:
    """Orchestrates scanning and analysis to construct a concise Markdown context summary."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.scanner = DirectoryScanner(self.workspace_root)
        self.analyzer = WorkspaceAnalyzer(self.workspace_root)

    def build_summary(self, goal: str = "") -> str:
        """Scan, analyze, and format the project context into a Markdown summary, optionally filtered by goal."""
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

        # Build dependency graph and run impact analysis
        from nakama_kun.workspace.impact_analyzer import ImpactAnalyzer
        analyzer = ImpactAnalyzer(self.workspace_root)
        try:
            analyzer.load_or_rebuild_graph()
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to load/rebuild dependency graph: {e}")

        # Load Architecture Summary from cache (or build if not exists)
        arch_summary = ""
        try:
            arch_summary_path = self.workspace_root / ".workspace" / "architecture_summary.md"
            if arch_summary_path.exists():
                arch_summary = arch_summary_path.read_text(encoding="utf-8")
            else:
                from nakama_kun.workspace.architecture_summary import ArchitectureSummaryBuilder
                builder = ArchitectureSummaryBuilder(self.workspace_root)
                arch_summary = builder.build_and_cache_summary(
                    snapshot, analyzer.index_service.symbols, analyzer.graph
                )
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to build/load architecture summary: {e}")

        # Build repository intelligence context if a goal is provided
        intelligence_lines = []
        if goal and analyzer.index_service.symbols:
            # 1. Search for keywords in the goal to find relevant symbols and files
            words = set(goal.replace(".", " ").replace("/", " ").replace("_", " ").replace("::", " ").split())
            
            relevant_symbols = []
            matched_files = set()
            for sym in analyzer.index_service.symbols:
                if sym.type != "import":
                    # Match name exactly or case-insensitively
                    if sym.name in words or sym.name.lower() in [w.lower() for w in words]:
                        relevant_symbols.append(sym)
                        matched_files.add(sym.file)
            
            # Also match files mentioned in the goal
            for f in snapshot.files:
                p = Path(f)
                if p.name in words or p.stem in words:
                    matched_files.add(f)

            # 2. Extract Relevant Symbol locations
            if relevant_symbols:
                intelligence_lines.append("\n### Relevant Symbol Locations")
                for sym in relevant_symbols:
                    parent_part = f" inside `{sym.parent}`" if sym.parent else ""
                    intelligence_lines.append(
                        f"- Symbol `{sym.name}` ({sym.type}){parent_part} is located in `{sym.file}` on line {sym.line}"
                    )

            # 3. Perform Impact Analysis for matched files / symbols
            impacted_entities = set()
            for f in matched_files:
                impacted_entities.update(analyzer.analyze_change_impact(f))
            for sym in relevant_symbols:
                impacted_entities.update(analyzer.analyze_change_impact(sym.name))

            # Filter out the matched targets themselves
            for f in matched_files:
                impacted_entities.discard(f)
            for sym in relevant_symbols:
                node_id = f"{sym.file}::{sym.parent}::{sym.name}" if sym.parent else f"{sym.file}::{sym.name}"
                impacted_entities.discard(node_id)
                impacted_entities.discard(sym.name)

            if impacted_entities:
                intelligence_lines.append("\n### Change Impact Analysis")
                intelligence_lines.append(
                    "Modifying the identified symbols or files may affect the following downstream components:"
                )
                for ie in sorted(list(impacted_entities))[:15]:  # limit to top 15 to keep prompt clean
                    if "::" in ie:
                        parts = ie.split("::")
                        symbol_name = parts[-1]
                        parent_name = parts[-2] if len(parts) > 2 else None
                        parent_str = f" in Class `{parent_name}`" if parent_name else ""
                        intelligence_lines.append(
                            f"- Symbol `{symbol_name}`{parent_str} (defined in `{parts[0]}`)"
                        )
                    else:
                        intelligence_lines.append(f"- File `{ie}`")
                if len(impacted_entities) > 15:
                    intelligence_lines.append(f"- ... and {len(impacted_entities) - 15} more components.")

        # Build combined summary
        lines = []
        lines.append("## Workspace Context Summary")
        lines.append(f"- **Project Root**: `{self.workspace_root.name}`")
        
        # Append main summary
        lines.append(summary_text)

        # Append symbols and architecture summary
        if arch_summary:
            lines.append("\n" + arch_summary)
        
        if intelligence_lines:
            lines.extend(intelligence_lines)

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
        tree: dict[str, Any] = {}
        root_files: list[str] = []

        # Process folders
        for folder in sorted(snapshot.folders):
            parts = Path(folder).parts
            current = tree
            for part in parts[:3]:
                if part not in current:
                    current[part] = {}
                current = current[part]

        # Process files
        for file_path in sorted(snapshot.files):
            parts = Path(file_path).parts
            if len(parts) == 1:
                root_files.append(parts[0])
            else:
                current = tree
                for part in parts[:-1][:3]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                if len(parts) <= 3:
                    current[parts[-1]] = None

        # Build output lines
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
                    output.append(f"{prefix}{connector}{key}")
                else:
                    output.append(f"{prefix}{connector}{key}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    recurse(val, new_prefix)

        recurse(tree, "")

        for file_name in root_files:
            output.append(f"├── {file_name}")

        unique_lines = []
        seen = set()
        for line in output:
            if line not in seen:
                unique_lines.append(line)
                seen.add(line)

        if len(unique_lines) > 40:
            truncated = unique_lines[:40]
            truncated.append("... (some directories/files truncated)")
            return truncated

        return unique_lines
