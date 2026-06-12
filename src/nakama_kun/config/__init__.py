"""
Configuration package for nakama_kun.

Extension point for Phase 2: settings, env vars, secrets management.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppConfig:
    """
    Central application configuration.

    Designed as an extension point — Phase 2 will populate fields such as
    llm_model, telegram_token, memory_backend, tool_registry, etc.
    """

    app_name: str = "nakama_kun"
    version: str = "0.1.0"
    debug: bool = False

    # Phase 2 extension points (intentionally empty for now)
    # llm_model: str = "gemini-2.0-flash"
    # telegram_token: str | None = None
    # memory_backend: str = "in_memory"

    # Future mode configs — populated by sub-packages
    modes: dict[str, dict[str, Any]] = field(default_factory=dict)


def find_env_file() -> str:
    """Locate a `.env` file by searching parent directories of CWD and the project package structure."""
    import os
    from pathlib import Path

    # 1. Search upwards from Current Working Directory
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd] + list(cwd.parents):
        env_path = parent / ".env"
        if env_path.is_file():
            return str(env_path)

    # 2. Search upwards from the package root directory
    pkg_file = Path(__file__).resolve()
    for parent in list(pkg_file.parents):
        env_path = parent / ".env"
        if env_path.is_file():
            return str(env_path)

    return ".env"  # Default fallback


def get_default_config() -> AppConfig:
    """Return the default application configuration."""
    return AppConfig()

