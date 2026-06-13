from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

from nakama_kun.workspace.models import ProjectSnapshot, Symbol


class RelationVisitor(ast.NodeVisitor):
    """AST visitor that finds symbol references, calls, and imports inside a Python file."""

    def __init__(
        self,
        file_path: str,
        symbol_map: dict[str, list[str]],
        file_imports: dict[str, str],
    ) -> None:
        self.file_path = file_path
        self.symbol_map = symbol_map
        self.file_imports = file_imports
        self.scope_stack: list[str] = [file_path]  # Starts with file as root scope
        self.relations: list[tuple[str, str, str]] = []  # (source_node, target_node, relation_type)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        node_id = f"{self.file_path}::{node.name}"
        # Handle nested classes
        parent_id = self.scope_stack[-1]
        if parent_id != self.file_path:
            node_id = f"{parent_id}::{node.name}"

        self.scope_stack.append(node_id)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent_id = self.scope_stack[-1]
        node_id = f"{self.file_path}::{node.name}"
        if parent_id != self.file_path:
            node_id = f"{parent_id}::{node.name}"

        self.scope_stack.append(node_id)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            target_node = self.file_imports.get(node.id)
            if not target_node:
                # Check locally defined symbol in the same file
                candidates = self.symbol_map.get(node.id, [])
                for c in candidates:
                    if c.startswith(f"{self.file_path}::"):
                        target_node = c
                        break

            if target_node:
                current_scope = self.scope_stack[-1]
                if current_scope != target_node:
                    self.relations.append((current_scope, target_node, "references"))

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        current_scope = self.scope_stack[-1]
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            target_node = self.file_imports.get(func_name)
            if not target_node:
                candidates = self.symbol_map.get(func_name, [])
                for c in candidates:
                    if c.startswith(f"{self.file_path}::"):
                        target_node = c
                        break
            if target_node:
                if current_scope != target_node:
                    self.relations.append((current_scope, target_node, "function_calls"))

        elif isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            # Match method calls heuristically by method name
            candidates = self.symbol_map.get(method_name, [])
            for c in candidates:
                if "::" in c:
                    self.relations.append((current_scope, c, "function_calls"))

        self.generic_visit(node)


class DependencyGraphBuilder:
    """Builder that parses the workspace file system and symbols into a NetworkX directed graph."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.graph = nx.DiGraph()

    def build_graph(self, snapshot: ProjectSnapshot, symbols: list[Symbol]) -> nx.DiGraph:
        """Create and populate nodes and edges for the dependency graph."""
        self.graph.clear()

        # 1. Add file nodes
        for f in snapshot.files:
            self.graph.add_node(f, type="file")

        # 2. Add symbol nodes
        for sym in symbols:
            if sym.type != "import":
                node_id = self._get_symbol_node_id(sym, symbols)
                self.graph.add_node(node_id, type=sym.type, name=sym.name, file=sym.file)

        # Map symbol name -> list of node IDs for fast resolution
        symbol_map: dict[str, list[str]] = {}
        for sym in symbols:
            if sym.type != "import":
                node_id = self._get_symbol_node_id(sym, symbols)
                symbol_map.setdefault(sym.name, []).append(node_id)

        # 3. Add ownership edges
        for sym in symbols:
            if sym.type != "import":
                node_id = self._get_symbol_node_id(sym, symbols)
                if sym.parent:
                    # Resolve correct parent node ID (handling nested classes/functions)
                    actual_parent = None
                    candidate = f"{sym.file}::{sym.parent}"
                    if self.graph.has_node(candidate):
                        actual_parent = candidate
                    else:
                        for n in self.graph.nodes:
                            if n.startswith(f"{sym.file}::") and n.endswith(f"::{sym.parent}"):
                                actual_parent = n
                                break
                    if actual_parent:
                        self.graph.add_edge(actual_parent, node_id, type="ownership")
                    else:
                        self.graph.add_edge(sym.file, node_id, type="ownership")
                else:
                    self.graph.add_edge(sym.file, node_id, type="ownership")

        # 4. Resolve imports and dependencies from AST
        for f in snapshot.files:
            if not f.endswith(".py"):
                continue
            full_path = self.workspace_root / f
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(full_path))
            except Exception:
                continue

            # Resolve imports in this file
            file_imports: dict[str, str] = {}
            for sym in symbols:
                if sym.file == f and sym.type == "import":
                    # Check if imported name represents a symbol defined in repo
                    targets = symbol_map.get(sym.name, [])
                    if targets:
                        file_imports[sym.name] = targets[0]
                    else:
                        # Resolve imported module to repo files
                        mod_path = sym.name.replace(".", "/")
                        for sf in snapshot.files:
                            if sf.endswith(f"{mod_path}.py") or sf.endswith(f"{mod_path}/__init__.py"):
                                file_imports[sym.name] = sf
                                break

            # Add import edges
            for imp_name, target in file_imports.items():
                if self.graph.has_node(f) and self.graph.has_node(target):
                    self.graph.add_edge(f, target, type="imports")

            # Extract internal references and calls
            visitor = RelationVisitor(f, symbol_map, file_imports)
            visitor.visit(tree)

            for u, v, rel_type in visitor.relations:
                if self.graph.has_node(u) and self.graph.has_node(v):
                    self.graph.add_edge(u, v, type=rel_type)

        return self.graph

    def _get_symbol_node_id(self, sym: Symbol, symbols: list[Symbol]) -> str:
        path_parts = [sym.name]
        curr_parent = sym.parent
        while curr_parent:
            path_parts.append(curr_parent)
            found = False
            for s in symbols:
                if s.file == sym.file and s.name == curr_parent and s.type == "class":
                    curr_parent = s.parent
                    found = True
                    break
            if not found:
                break
        path_parts.reverse()
        return f"{sym.file}::" + "::".join(path_parts)
