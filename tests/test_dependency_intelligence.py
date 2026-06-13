from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import networkx as nx
import pytest

from nakama_kun.workspace.models import ProjectSnapshot, Symbol, TestInfo as WorkspaceTestInfo, GitInfo
from nakama_kun.workspace.dependency_graph import DependencyGraphBuilder
from nakama_kun.workspace.impact_analyzer import ImpactAnalyzer
from nakama_kun.workspace.architecture_summary import ArchitectureSummaryBuilder
from nakama_kun.workspace.context import WorkspaceContextBuilder


def test_dependency_graph_builder_and_circular_imports(tmp_path: Path) -> None:
    # 1. Create files for circular import: a.py imports b.py, b.py imports a.py
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    file_a = src_dir / "a.py"
    file_a.write_text("import src.b\nclass ClassA:\n    pass\n")

    file_b = src_dir / "b.py"
    file_b.write_text("import src.a\nclass ClassB:\n    pass\n")

    snapshot = ProjectSnapshot(
        files=["src/a.py", "src/b.py"],
        folders=["src"],
        languages={"Python": 2},
        dependencies=[],
        entrypoints=[],
        tests=WorkspaceTestInfo(),
        git_info=GitInfo(),
    )
    
    symbols = [
        Symbol(name="ClassA", type="class", file="src/a.py", line=2, parent=None, decorators=[]),
        Symbol(name="ClassB", type="class", file="src/b.py", line=2, parent=None, decorators=[]),
        Symbol(name="src.b", type="import", file="src/a.py", line=1, parent=None, decorators=[]),
        Symbol(name="src.a", type="import", file="src/b.py", line=1, parent=None, decorators=[]),
    ]

    # 2. Build graph
    builder = DependencyGraphBuilder(workspace_root=tmp_path)
    graph = builder.build_graph(snapshot, symbols)

    # 3. Assertions
    # Nodes exist
    assert graph.has_node("src/a.py")
    assert graph.has_node("src/b.py")
    assert graph.has_node("src/a.py::ClassA")
    assert graph.has_node("src/b.py::ClassB")

    # Edges exist
    # Ownership
    assert graph.has_edge("src/a.py", "src/a.py::ClassA")
    # Circular imports edges: a.py imports b.py, b.py imports a.py
    assert graph.has_edge("src/a.py", "src/b.py")
    assert graph.has_edge("src/b.py", "src/a.py")


def test_nested_modules_and_ownership(tmp_path: Path) -> None:
    # Setup nested module
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    file_a = src_dir / "a.py"
    # Nested Class definition and methods
    file_a.write_text("""
class ParentClass:
    class NestedClass:
        def nested_method(self):
            pass
""")

    snapshot = ProjectSnapshot(
        files=["src/a.py"],
        folders=["src"],
        languages={"Python": 1},
        dependencies=[],
        entrypoints=[],
        tests=WorkspaceTestInfo(),
        git_info=GitInfo(),
    )
    
    symbols = [
        Symbol(name="ParentClass", type="class", file="src/a.py", line=2, parent=None, decorators=[]),
        Symbol(name="NestedClass", type="class", file="src/a.py", line=3, parent="ParentClass", decorators=[]),
        Symbol(name="nested_method", type="method", file="src/a.py", line=4, parent="NestedClass", decorators=[]),
    ]

    builder = DependencyGraphBuilder(workspace_root=tmp_path)
    graph = builder.build_graph(snapshot, symbols)

    # Verify nested structure ownership edges
    assert graph.has_node("src/a.py::ParentClass")
    assert graph.has_node("src/a.py::ParentClass::NestedClass")
    assert graph.has_node("src/a.py::ParentClass::NestedClass::nested_method")
    
    assert graph.has_edge("src/a.py", "src/a.py::ParentClass")
    assert graph.has_edge("src/a.py::ParentClass", "src/a.py::ParentClass::NestedClass")
    assert graph.has_edge("src/a.py::ParentClass::NestedClass", "src/a.py::ParentClass::NestedClass::nested_method")


def test_missing_files_handled_gracefully(tmp_path: Path) -> None:
    # Build snapshot with a file that doesn't actually exist
    snapshot = ProjectSnapshot(
        files=["src/missing.py"],
        folders=["src"],
        languages={"Python": 1},
        dependencies=[],
        entrypoints=[],
        tests=WorkspaceTestInfo(),
        git_info=GitInfo(),
    )
    symbols = []

    builder = DependencyGraphBuilder(workspace_root=tmp_path)
    # This should not raise exceptions
    graph = builder.build_graph(snapshot, symbols)
    
    assert graph.has_node("src/missing.py")
    assert len(graph.edges) == 0


def test_impact_analyzer_and_graph_rebuilds(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    file_a = src_dir / "a.py"
    file_a.write_text("import src.b\nclass ClassA:\n    pass\n")

    file_b = src_dir / "b.py"
    file_b.write_text("class ClassB:\n    pass\n")

    # Rebuild snapshot and symbol index caches using mock/services
    analyzer = ImpactAnalyzer(workspace_root=tmp_path)
    
    # Pre-write snapshot
    snapshot_dir = tmp_path / ".workspace"
    snapshot_dir.mkdir()
    snapshot = ProjectSnapshot(
        files=["src/a.py", "src/b.py"],
        folders=["src"],
        languages={"Python": 2},
        dependencies=[],
        entrypoints=[],
        tests=WorkspaceTestInfo(),
        git_info=GitInfo(),
    )
    with open(snapshot_dir / "workspace_snapshot.json", "w", encoding="utf-8") as f:
        f.write(snapshot.model_dump_json(indent=2))

    # Trigger load/rebuild
    analyzer.load_or_rebuild_graph()
    
    # Verify file-level dependents/dependencies
    assert "src/b.py" in analyzer.get_dependencies("src/a.py")
    assert "src/a.py" in analyzer.get_dependents("src/b.py")
    
    # Impact: changing b.py should affect a.py
    impact = analyzer.analyze_change_impact("src/b.py")
    assert "src/a.py" in impact

    # Graph rebuild invalidation test
    # Rebuilding index triggers rebuilding graph. Touch index mtime or modify code.
    time.sleep(0.01)
    file_a.write_text("class ClassA:\n    pass\n")
    
    # Rebuild symbol index
    analyzer.index_service.load_or_rebuild()
    analyzer.load_or_rebuild_graph()
    
    # Success: b.py dependency should now be removed
    assert "src/b.py" not in analyzer.get_dependencies("src/a.py")


def test_architecture_summary_builder(tmp_path: Path) -> None:
    snapshot = ProjectSnapshot(
        files=["src/nakama_kun/main.py", "src/nakama_kun/tools/core/write_file.py"],
        folders=["src", "src/nakama_kun", "src/nakama_kun/tools", "src/nakama_kun/tools/core"],
        languages={"Python": 2},
        dependencies=[],
        entrypoints=["src/nakama_kun/main.py"],
        tests=WorkspaceTestInfo(),
        git_info=GitInfo(),
    )

    symbols = [
        Symbol(name="write_file", type="function", file="src/nakama_kun/tools/core/write_file.py", line=1, parent=None, decorators=[])
    ]

    graph = nx.DiGraph()
    graph.add_node("src/nakama_kun/main.py", type="file")
    graph.add_node("src/nakama_kun/tools/core/write_file.py", type="file")

    builder = ArchitectureSummaryBuilder(workspace_root=tmp_path)
    summary = builder.build_and_cache_summary(snapshot, symbols, graph)

    assert "Codebase Architecture Summary" in summary
    assert "Project Type" in summary
    assert "src/nakama_kun/main.py" in summary
    assert "write_file" in summary
    assert "Main Execution Flow" in summary

    # Verify cached file is created
    assert (tmp_path / ".workspace" / "architecture_summary.md").exists()


def test_context_builder_planner_intelligence(tmp_path: Path) -> None:
    # 1. Setup repository structure
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    file_a = src_dir / "scanner.py"
    file_a.write_text("class WorkspaceScanner:\n    pass\n")

    # Trigger scan & symbol cache creation
    builder = WorkspaceContextBuilder(workspace_root=tmp_path)
    summary_without_goal = builder.build_summary()
    assert "Codebase Architecture Summary" in summary_without_goal

    # Query with a goal referencing 'WorkspaceScanner'
    summary_with_goal = builder.build_summary(goal="Fix bugs in WorkspaceScanner and scanner.py")
    
    # Output should include Relevant Symbol Locations and Change Impact Analysis
    assert "Relevant Symbol Locations" in summary_with_goal
    assert "WorkspaceScanner" in summary_with_goal
    assert "scanner.py" in summary_with_goal
