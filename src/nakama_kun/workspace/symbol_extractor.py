from __future__ import annotations

import ast
from pathlib import Path
from nakama_kun.workspace.models import Symbol


class SymbolVisitor(ast.NodeVisitor):
    """AST visitor that extracts symbols from a Python file structure."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.symbols: list[Symbol] = []
        self.scope_stack: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            self.symbols.append(
                Symbol(
                    name=name,
                    type="import",
                    file=self.file_path,
                    line=node.lineno,
                    parent=None,
                    decorators=[],
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            self.symbols.append(
                Symbol(
                    name=name,
                    type="import",
                    file=self.file_path,
                    line=node.lineno,
                    parent=None,
                    decorators=[],
                )
            )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol_name = node.name
        parent_name = self.scope_stack[-1] if self.scope_stack else None
        decorators = self._extract_decorators(node.decorator_list)

        self.symbols.append(
            Symbol(
                name=symbol_name,
                type="class",
                file=self.file_path,
                line=node.lineno,
                parent=parent_name,
                decorators=decorators,
            )
        )

        self.scope_stack.append(symbol_name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        symbol_name = node.name
        parent_name = self.scope_stack[-1] if self.scope_stack else None

        # Determine if it's a method: parent_name exists and corresponds to a ClassDef
        is_method = False
        if parent_name:
            # Check if parent is a class in our symbols
            for sym in self.symbols:
                if sym.name == parent_name and sym.type == "class":
                    is_method = True
                    break

        symbol_type = "method" if is_method else "function"
        decorators = self._extract_decorators(node.decorator_list)

        self.symbols.append(
            Symbol(
                name=symbol_name,
                type=symbol_type,
                file=self.file_path,
                line=node.lineno,
                parent=parent_name,
                decorators=decorators,
            )
        )

        self.scope_stack.append(symbol_name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def _extract_decorators(self, decorator_list: list[ast.expr]) -> list[str]:
        decorators = []
        for dec in decorator_list:
            try:
                dec_str = ast.unparse(dec).strip()
                decorators.append(dec_str)
            except Exception:
                pass
        return decorators


class PythonSymbolExtractor:
    """Extractor that parses a Python file and returns a list of its Symbol definitions."""

    def __init__(self, file_path: str, workspace_root: Path) -> None:
        self.file_path = file_path
        self.workspace_root = workspace_root

    def extract(self) -> list[Symbol]:
        """Read and parse the file to extract symbols."""
        full_path = self.workspace_root / self.file_path
        if not full_path.exists():
            return []

        try:
            content = full_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(full_path))
        except Exception:
            # Return empty if syntax errors or read errors occur
            return []

        visitor = SymbolVisitor(self.file_path)
        visitor.visit(tree)
        return visitor.symbols
