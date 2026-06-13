from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from nakama_kun.workspace.symbol_index_service import SymbolIndexService


class PlannerContextBuilder:
    """Builder providing workspace code intelligence (symbol locations, module ownership) for the planner."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.index_service = SymbolIndexService(self.workspace_root)

    def get_function_locations(self) -> dict[str, list[dict[str, Any]]]:
        """Get mappings from function/method name to list of locations."""
        self.index_service.load_or_rebuild()
        locations: dict[str, list[dict[str, Any]]] = {}

        for sym in self.index_service.symbols:
            if sym.type in ("function", "method"):
                locations.setdefault(sym.name, []).append({
                    "file": sym.file,
                    "line": sym.line,
                    "parent": sym.parent,
                    "type": sym.type,
                })
        return locations

    def get_class_locations(self) -> dict[str, list[dict[str, Any]]]:
        """Get mappings from class name to list of locations."""
        self.index_service.load_or_rebuild()
        locations: dict[str, list[dict[str, Any]]] = {}

        for sym in self.index_service.symbols:
            if sym.type == "class":
                locations.setdefault(sym.name, []).append({
                    "file": sym.file,
                    "line": sym.line,
                    "parent": sym.parent,
                })
        return locations

    def get_module_ownership(self) -> dict[str, list[dict[str, Any]]]:
        """Get mappings from module paths to symbols defined within them."""
        self.index_service.load_or_rebuild()
        ownership: dict[str, list[dict[str, Any]]] = {}

        for sym in self.index_service.symbols:
            # We exclude imports for general module ownership
            if sym.type != "import":
                ownership.setdefault(sym.file, []).append({
                    "name": sym.name,
                    "type": sym.type,
                    "line": sym.line,
                    "parent": sym.parent,
                })
        return ownership

    def build_symbol_summary(self) -> str:
        """Construct a structured Markdown summary listing classes, functions, and locations."""
        self.index_service.load_or_rebuild()
        symbols = self.index_service.symbols

        lines = ["## Workspace Symbol Index"]
        if not symbols:
            lines.append("No symbols indexed.")
            return "\n".join(lines)

        # Group symbols by module (file)
        by_file: dict[str, list[Any]] = {}
        for sym in symbols:
            if sym.type != "import":  # Omit imports to keep prompt compact and clean
                by_file.setdefault(sym.file, []).append(sym)

        if not by_file:
            lines.append("No class/function/method symbols found.")
            return "\n".join(lines)

        for file_path, syms in sorted(by_file.items()):
            lines.append(f"- **Module `{file_path}`** owns:")
            sorted_syms = sorted(syms, key=lambda s: s.line)
            for sym in sorted_syms:
                if sym.type == "class":
                    lines.append(f"  - Class `{sym.name}` (line {sym.line})")
                elif sym.type == "function":
                    lines.append(f"  - Function `{sym.name}` (line {sym.line})")
                elif sym.type == "method":
                    parent_part = f"{sym.parent}." if sym.parent else ""
                    lines.append(f"  - Method `{parent_part}{sym.name}` (line {sym.line})")

        return "\n".join(lines)
