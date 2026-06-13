from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from nakama_kun.workspace.models import Symbol
from nakama_kun.workspace.symbol_extractor import PythonSymbolExtractor
from nakama_kun.workspace.symbol_index_service import SymbolIndexService
from nakama_kun.workspace.planner_context import PlannerContextBuilder


def test_python_symbol_extractor(tmp_path: Path) -> None:
    # 1. Setup python code covering nested classes, methods, imports, and decorators
    code = """
import os
from datetime import datetime as dt

@logger.info("decorating outer class")
class OuterClass:
    class NestedClass:
        @classmethod
        def nested_method(cls):
            pass

    def outer_method(self):
        pass

@my_decorator
def global_function():
    pass
"""
    file_path = tmp_path / "src" / "test_module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(code)

    extractor = PythonSymbolExtractor("src/test_module.py", workspace_root=tmp_path)
    symbols = extractor.extract()

    # 2. Assertions
    # We should have os and dt as imports
    imports = [s for s in symbols if s.type == "import"]
    assert any(s.name == "os" for s in imports)
    assert any(s.name == "dt" for s in imports)

    # Classes
    classes = [s for s in symbols if s.type == "class"]
    assert len(classes) == 2
    outer_class = next(s for s in classes if s.name == "OuterClass")
    assert outer_class.parent is None
    assert 'logger.info("decorating outer class")' in outer_class.decorators or "logger.info('decorating outer class')" in outer_class.decorators

    nested_class = next(s for s in classes if s.name == "NestedClass")
    assert nested_class.parent == "OuterClass"

    # Methods
    methods = [s for s in symbols if s.type == "method"]
    assert len(methods) == 2
    nested_method = next(s for s in methods if s.name == "nested_method")
    assert nested_method.parent == "NestedClass"
    assert "classmethod" in nested_method.decorators

    outer_method = next(s for s in methods if s.name == "outer_method")
    assert outer_method.parent == "OuterClass"

    # Functions
    functions = [s for s in symbols if s.type == "function"]
    assert len(functions) == 1
    global_func = functions[0]
    assert global_func.name == "global_function"
    assert "my_decorator" in global_func.decorators
    assert global_func.parent is None


def test_symbol_index_service_apis_and_invalidation(tmp_path: Path) -> None:
    # 1. Setup files
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    file_a = src_dir / "a.py"
    file_a.write_text("class ClassA:\n    pass\n")

    file_b = src_dir / "b.py"
    file_b.write_text("def func_b():\n    pass\n")

    # 2. Run index service
    service = SymbolIndexService(workspace_root=tmp_path)
    service.load_or_rebuild()

    # Verify cache is created
    cache_file = tmp_path / ".workspace" / "symbol_index.json"
    assert cache_file.exists()

    # 3. Test APIs
    syms_a = service.find_symbol("ClassA")
    assert len(syms_a) == 1
    assert syms_a[0].type == "class"
    assert syms_a[0].file == "src/a.py"

    funcs = service.find_symbols_by_type("function")
    assert len(funcs) == 1
    assert funcs[0].name == "func_b"

    file_a_syms = service.find_symbols_in_file("src/a.py")
    assert len(file_a_syms) == 1
    assert file_a_syms[0].name == "ClassA"

    # 4. Invalidation Test: modify file_a and check rebuild
    # Sleep slightly to ensure mtime changes
    time.sleep(0.01)
    file_a.write_text("class ClassA:\n    pass\nclass ClassNew:\n    pass\n")
    # Touch mtime explicitly just in case filesystem resolution is coarse
    mtime = time.time() + 10.0
    os.utime(file_a, (mtime, mtime))

    # Triggering query API should detect the invalidation and reload/rebuild
    new_syms = service.find_symbol("ClassNew")
    assert len(new_syms) == 1
    assert new_syms[0].file == "src/a.py"

    # 5. Invalidation Test: delete file_b and check rebuild
    file_b.unlink()
    funcs_after_delete = service.find_symbols_by_type("function")
    assert len(funcs_after_delete) == 0


def test_planner_context_builder(tmp_path: Path) -> None:
    # Create test symbols
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    file_a = src_dir / "a.py"
    file_a.write_text("class ClassA:\n    def method_a(self):\n        pass\n")

    builder = PlannerContextBuilder(workspace_root=tmp_path)
    
    # Test class locations
    class_locs = builder.get_class_locations()
    assert "ClassA" in class_locs
    assert class_locs["ClassA"][0]["file"] == "src/a.py"

    # Test function/method locations
    func_locs = builder.get_function_locations()
    assert "method_a" in func_locs
    assert func_locs["method_a"][0]["file"] == "src/a.py"
    assert func_locs["method_a"][0]["parent"] == "ClassA"

    # Test module ownership
    ownership = builder.get_module_ownership()
    assert "src/a.py" in ownership
    owned_syms = [s["name"] for s in ownership["src/a.py"]]
    assert "ClassA" in owned_syms
    assert "method_a" in owned_syms

    # Test summary builder
    summary = builder.build_symbol_summary()
    assert "## Workspace Symbol Index" in summary
    assert "Module `src/a.py`" in summary
    assert "Class `ClassA`" in summary
    assert "Method `ClassA.method_a`" in summary
