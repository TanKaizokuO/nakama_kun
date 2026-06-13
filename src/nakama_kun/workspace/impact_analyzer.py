from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

from nakama_kun.workspace.symbol_index_service import SymbolIndexService


class ImpactAnalyzer:
    """Service that queries code dependency patterns and calculates change impacts."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.graph_path = self.workspace_root / ".workspace" / "dependency_graph.json"
        self.index_service = SymbolIndexService(self.workspace_root)
        self.graph = nx.DiGraph()

    def load_or_rebuild_graph(self) -> None:
        """Load the cached dependency graph if valid; otherwise, rebuild it."""
        self.index_service.load_or_rebuild()

        symbol_index_path = self.index_service.cache_path
        rebuild_needed = not self.graph_path.exists()

        if not rebuild_needed and symbol_index_path.exists():
            # If symbol index is newer than dependency graph, it means workspace files changed
            rebuild_needed = symbol_index_path.stat().st_mtime > self.graph_path.stat().st_mtime

        if rebuild_needed:
            self.rebuild_graph()
        else:
            try:
                with open(self.graph_path, encoding="utf-8") as f:
                    data = json.load(f)
                self.graph = json_graph.node_link_graph(data)
            except Exception:
                self.rebuild_graph()

    def rebuild_graph(self) -> None:
        """Extract workspace snapshot details and rebuild the NetworkX DiGraph."""
        snapshot_path = self.workspace_root / ".workspace" / "workspace_snapshot.json"
        
        # Safe load snapshot
        from nakama_kun.workspace.models import ProjectSnapshot
        try:
            with open(snapshot_path, encoding="utf-8") as f:
                snapshot = ProjectSnapshot.model_validate_json(f.read())
        except Exception:
            from nakama_kun.workspace.scanner_service import WorkspaceScanner
            scanner = WorkspaceScanner(self.workspace_root)
            snapshot = scanner.scan()

        from nakama_kun.workspace.dependency_graph import DependencyGraphBuilder
        builder = DependencyGraphBuilder(self.workspace_root)
        self.graph = builder.build_graph(snapshot, self.index_service.symbols)

        # Cache the graph
        self.graph_path.parent.mkdir(exist_ok=True)
        try:
            data = json_graph.node_link_data(self.graph)
            with open(self.graph_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # --- APIs ---

    def get_dependencies(self, node: str) -> list[str]:
        """Return direct dependencies of a node (outgoing edges / successors)."""
        self.load_or_rebuild_graph()
        if self.graph.has_node(node):
            return sorted(list(self.graph.successors(node)))
        return []

    def get_dependents(self, node: str) -> list[str]:
        """Return direct dependents of a node (incoming edges / predecessors)."""
        self.load_or_rebuild_graph()
        if self.graph.has_node(node):
            return sorted(list(self.graph.predecessors(node)))
        return []

    def analyze_change_impact(self, target: str) -> list[str]:
        """Find all upstream entities impacted by changing the target file or symbol name."""
        self.load_or_rebuild_graph()

        # 1. Exact node match
        if self.graph.has_node(target):
            return self._bfs_impact(target)

        # 2. File path match (relative path normalization)
        norm_path = target
        try:
            norm_path = str(Path(target).resolve().relative_to(self.workspace_root))
        except Exception:
            if norm_path.startswith("./") or norm_path.startswith(".\\"):
                norm_path = norm_path[2:]

        if self.graph.has_node(norm_path):
            return self._bfs_impact(norm_path)

        # 3. Symbol name match (find all nodes representing the symbol name)
        matching_nodes = []
        for node in self.graph.nodes:
            parts = node.split("::")
            if len(parts) > 1 and parts[-1] == target:
                matching_nodes.append(node)

        if matching_nodes:
            impacted = set()
            for mn in matching_nodes:
                impacted.update(self._bfs_impact(mn))
            # Exclude the matching nodes themselves
            for mn in matching_nodes:
                impacted.discard(mn)
            return sorted(list(impacted))

        return []

    def _bfs_impact(self, start_node: str) -> list[str]:
        """Run BFS on the reversed graph to discover all dependents recursively."""
        visited = {start_node}
        queue = [start_node]
        impacted = []
        rev_graph = self.graph.reverse()

        while queue:
            curr = queue.pop(0)
            for neighbor in rev_graph.neighbors(curr):
                if neighbor not in visited:
                    visited.add(neighbor)
                    impacted.append(neighbor)
                    queue.append(neighbor)

        return impacted
