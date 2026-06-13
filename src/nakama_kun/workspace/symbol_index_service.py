from __future__ import annotations

import json
import os
from datetime import datetime, UTC
from pathlib import Path

from nakama_kun.workspace.scanner import DirectoryScanner
from nakama_kun.workspace.symbol_extractor import PythonSymbolExtractor
from nakama_kun.workspace.models import Symbol


class SymbolIndexService:
    """Service managing workspace symbol indexing, caching, searching, and change invalidation."""

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.cache_path = self.workspace_root / ".workspace" / "symbol_index.json"
        self.symbols: list[Symbol] = []
        self.files_mtime: dict[str, float] = {}

    def load_or_rebuild(self) -> None:
        """Load symbols from cache if valid; otherwise scan and rebuild the index."""
        # 1. Scan the repository using DirectoryScanner to find all Python files
        scanner = DirectoryScanner(self.workspace_root)
        scan_result = scanner.scan()
        py_files = [f.path for f in scan_result.files if f.extension == ".py"]

        # 2. Get current modified times for all py_files
        current_mtimes: dict[str, float] = {}
        for path in py_files:
            full_path = self.workspace_root / path
            if full_path.exists():
                try:
                    current_mtimes[path] = full_path.stat().st_mtime
                except OSError:
                    pass

        # 3. Check if we can load from cache
        if self._is_cache_valid(current_mtimes):
            self.load_from_cache()
            return

        # 4. Cache is invalid or missing, rebuild it
        self.rebuild(py_files, current_mtimes)

    def _is_cache_valid(self, current_mtimes: dict[str, float]) -> bool:
        """Check if cached index matches all current file mtimes and file counts."""
        if not self.cache_path.exists():
            return False

        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)

            cached_mtimes = data.get("metadata", {}).get("files_mtime", {})

            # Check if file counts match
            if len(cached_mtimes) != len(current_mtimes):
                return False

            # Check if all files in current exist in cached and match mtime
            for path, current_mtime in current_mtimes.items():
                if path not in cached_mtimes:
                    return False
                # Use a small delta for float comparison (to handle precision discrepancies)
                if abs(cached_mtimes[path] - current_mtime) > 1e-4:
                    return False

            return True
        except Exception:
            return False

    def load_from_cache(self) -> None:
        """Read symbols from cached symbol_index.json."""
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)

            self.files_mtime = data.get("metadata", {}).get("files_mtime", {})
            self.symbols = [Symbol(**s) for s in data.get("symbols", [])]
        except Exception:
            # Fall back to empty lists if reading fails
            self.symbols = []
            self.files_mtime = {}

    def rebuild(self, py_files: list[str], current_mtimes: dict[str, float]) -> None:
        """Re-extract symbols from py_files and save them to the cache."""
        self.symbols = []
        self.files_mtime = current_mtimes

        for path in py_files:
            extractor = PythonSymbolExtractor(path, self.workspace_root)
            self.symbols.extend(extractor.extract())

        # Save to disk
        self._save_cache()

    def _save_cache(self) -> None:
        """Serialize symbols and metadata to symbol_index.json."""
        self.cache_path.parent.mkdir(exist_ok=True)

        data = {
            "metadata": {
                "generated_at": datetime.now(UTC).isoformat(),
                "files_mtime": self.files_mtime,
            },
            "symbols": [s.model_dump() for s in self.symbols]
        }

        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    # --- APIs ---

    def find_symbol(self, name: str) -> list[Symbol]:
        """Find symbols by name (exact match)."""
        self.load_or_rebuild()
        return [s for s in self.symbols if s.name == name]

    def find_symbols_by_type(self, symbol_type: str) -> list[Symbol]:
        """Find symbols of a specific type (e.g. 'class', 'function', 'method', 'import')."""
        self.load_or_rebuild()
        return [s for s in self.symbols if s.type == symbol_type]

    def find_symbols_in_file(self, path: str) -> list[Symbol]:
        """Find all symbols defined in a specific file."""
        self.load_or_rebuild()
        try:
            normalized_path = str(Path(path).resolve().relative_to(self.workspace_root))
        except Exception:
            normalized_path = str(Path(path))
            if normalized_path.startswith("./") or normalized_path.startswith(".\\"):
                normalized_path = normalized_path[2:]

        return [
            s for s in self.symbols
            if s.file == normalized_path or Path(s.file).resolve() == Path(path).resolve()
        ]
