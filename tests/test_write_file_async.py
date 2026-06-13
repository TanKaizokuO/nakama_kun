from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nakama_kun.safety.manager import SafetyManager
from nakama_kun.safety.terminal import TerminalApprovalProvider
from nakama_kun.tools.core.write_file import WriteFileTool


@pytest.mark.anyio
async def test_write_file_create(tmp_path: Path) -> None:
    """Verify write_file creates a new file successfully."""
    tool = WriteFileTool(str(tmp_path))
    target = tmp_path / "new_file.txt"
    
    # Catch warnings to ensure no RuntimeWarning about unawaited coroutine is raised
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        
        result = await tool.execute(path=str(target), content="hello new file")
        
        assert result.success
        assert result.output is not None
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "hello new file"
        
        # Verify no RuntimeWarning occurred
        runtime_warnings = [
            w for w in caught_warnings if issubclass(w.category, RuntimeWarning)
        ]
        assert len(runtime_warnings) == 0, f"Triggered warnings: {runtime_warnings}"


@pytest.mark.anyio
async def test_write_file_modify(tmp_path: Path) -> None:
    """Verify write_file modifies an existing file successfully."""
    tool = WriteFileTool(str(tmp_path))
    target = tmp_path / "exist.txt"
    target.write_text("initial content", encoding="utf-8")
    
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        
        result = await tool.execute(path=str(target), content="modified content")
        
        assert result.success
        assert target.read_text(encoding="utf-8") == "modified content"
        
        runtime_warnings = [
            w for w in caught_warnings if issubclass(w.category, RuntimeWarning)
        ]
        assert len(runtime_warnings) == 0


@pytest.mark.anyio
async def test_write_file_overwrite(tmp_path: Path) -> None:
    """Verify write_file overwrites a file successfully."""
    tool = WriteFileTool(str(tmp_path))
    target = tmp_path / "overwrite_test.txt"
    target.write_text("old text", encoding="utf-8")
    
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        
        result = await tool.execute(path=str(target), content="new text")
        
        assert result.success
        assert target.read_text(encoding="utf-8") == "new text"
        
        runtime_warnings = [
            w for w in caught_warnings if issubclass(w.category, RuntimeWarning)
        ]
        assert len(runtime_warnings) == 0


@pytest.mark.anyio
async def test_write_file_nested_dir(tmp_path: Path) -> None:
    """Verify write_file creates parent directories if they don't exist."""
    tool = WriteFileTool(str(tmp_path))
    target = tmp_path / "nested" / "dir" / "structure" / "file.txt"
    
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        
        result = await tool.execute(path=str(target), content="nested content")
        
        assert result.success
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "nested content"
        
        runtime_warnings = [
            w for w in caught_warnings if issubclass(w.category, RuntimeWarning)
        ]
        assert len(runtime_warnings) == 0


@pytest.mark.anyio
async def test_write_file_terminal_approval_provider_async(tmp_path: Path) -> None:
    """Verify TerminalApprovalProvider request_approval behaves correctly when called asynchronously."""
    manager = SafetyManager(workspace_root=tmp_path)
    provider = TerminalApprovalProvider()
    
    # Mock questionary to return True/False asynchronously via ask_async
    mock_confirm = MagicMock()
    mock_confirm.ask_async = AsyncMock(return_value=True)
    
    tool = WriteFileTool(
        workspace_root=str(tmp_path),
        safety_manager=manager,
        approval_provider=provider,
    )
    target = tmp_path / "approved.txt"
    
    with patch("questionary.confirm", return_value=mock_confirm), warnings.catch_warnings(
        record=True
    ) as caught_warnings:
        warnings.simplefilter("always")
        
        result = await tool.execute(path=str(target), content="approved content")
        
        assert result.success
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "approved content"
        
        # Ensure prompt was confirmed asynchronously
        mock_confirm.ask_async.assert_called_once()
        
        # Verify no RuntimeWarning occurred
        runtime_warnings = [
            w for w in caught_warnings if issubclass(w.category, RuntimeWarning)
        ]
        assert len(runtime_warnings) == 0
