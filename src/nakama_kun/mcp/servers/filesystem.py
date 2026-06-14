from __future__ import annotations

import os
import glob
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("filesystem")


@mcp.tool()
def read_file(path: str) -> str:
    """Read the content of a file.

    Permissions: filesystem_read
    Categories: filesystem
    Usage: Retrieve the contents of a file as a string.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"ERROR: Failed to read file: {e}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file.

    Permissions: filesystem_write
    Categories: filesystem
    Usage: Create or overwrite a file with specific text content.
    """
    try:
        abs_path = os.path.abspath(path)
        dir_name = os.path.dirname(abs_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"File written successfully to {path}"
    except Exception as e:
        return f"ERROR: Failed to write file: {e}"


@mcp.tool()
def list_directory(path: str) -> list[str]:
    """List all files and subdirectories in a directory.

    Permissions: filesystem_read
    Categories: filesystem
    Usage: Retrieve a list of paths representing contents of a directory.
    """
    try:
        if not os.path.exists(path):
            return [f"ERROR: Directory '{path}' does not exist"]
        return sorted(os.listdir(path))
    except Exception as e:
        return [f"ERROR: Failed to list directory: {e}"]


@mcp.tool()
def search_files(path: str, pattern: str) -> list[str]:
    """Search for files matching a pattern inside a directory.

    Permissions: filesystem_read
    Categories: filesystem
    Usage: Search recursively or flat matching glob patterns.
    """
    try:
        if not os.path.exists(path):
            return [f"ERROR: Base path '{path}' does not exist"]

        search_path = os.path.join(path, "**", pattern)
        results = glob.glob(search_path, recursive=True)
        return sorted([os.path.abspath(r) for r in results])
    except Exception as e:
        return [f"ERROR: File search failed: {e}"]


if __name__ == "__main__":
    mcp.run()
