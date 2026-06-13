from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nakama_kun.config import find_env_file


class MCPServerConfig(BaseModel):
    """Pydantic model representing stdio configuration for an external MCP server."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None


class MCPSettings(BaseSettings):
    """Configuration settings for nakama_kun's MCP client integration."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mcp_config_path: str = Field(
        default="mcp_config.json", validation_alias="MCP_CONFIG_PATH"
    )

    mcp_servers_json: str | None = Field(
        default=None, validation_alias="MCP_SERVERS_JSON"
    )

    def load_servers(self, workspace_root: str | None = None) -> dict[str, MCPServerConfig]:
        """Loads and parses the MCP server configurations.

        Checks the MCP_SERVERS_JSON environment variable first, falling back to
        the mcp_config.json file in the workspace root.
        """
        # 1. Try MCP_SERVERS_JSON environment variable
        if self.mcp_servers_json:
            try:
                data = json.loads(self.mcp_servers_json)
                return self._parse_servers_dict(data)
            except Exception as e:
                logger.warning(f"Failed to parse MCP_SERVERS_JSON env var: {e}")

        # 2. Try the config file in the workspace
        root = Path(workspace_root or os.getcwd()).resolve()
        config_file = root / self.mcp_config_path
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                return self._parse_servers_dict(data)
            except Exception as e:
                logger.warning(f"Failed to read or parse MCP config file at {config_file}: {e}")

        return {}

    def _parse_servers_dict(self, data: dict[str, Any]) -> dict[str, MCPServerConfig]:
        """Helper to extract server configurations from standard or flat JSON dictionaries."""
        if not isinstance(data, dict):
            logger.warning("MCP config JSON data is not a dictionary.")
            return {}

        # Handle standard Claude format: {"mcpServers": { ... }}
        servers_dict = data.get("mcpServers") or data.get("mcp_servers")
        if servers_dict is not None and isinstance(servers_dict, dict):
            target = servers_dict
        else:
            target = data

        parsed: dict[str, MCPServerConfig] = {}
        for name, cfg in target.items():
            if isinstance(cfg, dict):
                if "command" in cfg:
                    try:
                        parsed[name] = MCPServerConfig.model_validate(cfg)
                    except Exception as e:
                        logger.warning(f"Skipping invalid server config for '{name}': {e}")
                else:
                    logger.warning(f"Skipping server '{name}': 'command' field is missing.")

        return parsed
