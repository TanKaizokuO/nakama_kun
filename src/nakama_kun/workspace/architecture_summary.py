from __future__ import annotations

from pathlib import Path
import networkx as nx

from nakama_kun.workspace.models import ProjectSnapshot, Symbol


class ArchitectureSummaryBuilder:
    """Builds a comprehensive architectural summary of the codebase."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def build_and_cache_summary(
        self, snapshot: ProjectSnapshot, symbols: list[Symbol], graph: nx.DiGraph
    ) -> str:
        """Analyze project structure and generate cached architecture_summary.md."""
        # 1. Project Type
        project_type = "Python Project"
        if "package.json" in [Path(f).name for f in snapshot.files]:
            project_type = "Node.js/JavaScript Project"

        # 2. Entrypoints
        entrypoints_str = (
            "\n".join(f"- `{ep}`" for ep in snapshot.entrypoints)
            if snapshot.entrypoints
            else "- None detected"
        )

        # 3. Core Components (group files by their direct folder under src/nakama_kun/)
        core_folders: dict[str, list[str]] = {}
        for f in snapshot.files:
            p = Path(f)
            if len(p.parts) >= 3 and p.parts[0] == "src" and p.parts[1] == "nakama_kun":
                component = p.parts[2]
                if component != "__pycache__":
                    core_folders.setdefault(component, []).append(f)

        core_components_lines = []
        for comp, comp_files in sorted(core_folders.items()):
            file_count = len(comp_files)
            # Find key classes in this component
            comp_symbols = [
                s for s in symbols if s.file in comp_files and s.type == "class"
            ]
            syms_str = ", ".join(f"`{s.name}`" for s in comp_symbols[:3])
            if syms_str:
                core_components_lines.append(
                    f"- **{comp.capitalize()}** (`{comp_files[0].split('/')[0]}...`): Contains {file_count} files. Key classes: {syms_str}."
                )
            else:
                core_components_lines.append(
                    f"- **{comp.capitalize()}** (`{comp_files[0].split('/')[0]}...`): Contains {file_count} files."
                )

        core_components_str = (
            "\n".join(core_components_lines) if core_components_lines else "- None detected"
        )

        # 4. Tool Inventory
        tools_list = []
        for sym in symbols:
            if (
                sym.file.startswith("src/nakama_kun/tools/")
                and sym.type in ("class", "function")
                and sym.parent is None
            ):
                if not any(
                    x in sym.file
                    for x in ("router", "registry", "interfaces", "exceptions", "safety")
                ):
                    tools_list.append(f"- `{sym.name}` (defined in `{sym.file}`)")

        # Deduplicate and sort
        tools_list = sorted(list(set(tools_list)))
        tool_inventory_str = (
            "\n".join(tools_list) if tools_list else "- None detected"
        )

        # 5. Main Execution Flow
        main_flow_str = (
            "1. **CLI Wakeup**: The CLI entrypoint `src/nakama_kun/main.py` dispatches commands to `cli/` handlers.\n"
            "2. **Orchestration**: The orchestrator triggers LangGraph workflow nodes in `orchestration/nodes.py`.\n"
            "3. **Planner Node**: Decomposes the user goal into discrete required file targets & actions.\n"
            "4. **Coder Node**: Proposes file modifications based on the generated plan.\n"
            "5. **Executor Node**: Executes proposed changes using tools in `tools/` and tracks progress.\n"
            "6. **Reviewer Node**: Verifies changes and outputs validation reports, looping if errors occur."
        )

        summary_md = f"""# Codebase Architecture Summary

## Project Metadata
- **Project Type**: {project_type}
- **Total Files**: {len(snapshot.files)} files
- **Languages**: Python is the dominant language.

## Entrypoints
{entrypoints_str}

## Core Components
{core_components_str}

## Tool Inventory
{tool_inventory_str}

## Main Execution Flow
{main_flow_str}
"""

        # Write to cache
        cache_path = self.workspace_root / ".workspace" / "architecture_summary.md"
        cache_path.parent.mkdir(exist_ok=True)
        try:
            cache_path.write_text(summary_md, encoding="utf-8")
        except Exception:
            pass

        return summary_md
