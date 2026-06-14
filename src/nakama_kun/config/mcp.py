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

        Merges configurations from environment variables, mcp_config.json, and mcp.yaml.
        """
        # 1. Load baseline JSON configurations
        json_servers: dict[str, MCPServerConfig] = {}
        if self.mcp_servers_json:
            try:
                data = json.loads(self.mcp_servers_json)
                json_servers = self._parse_servers_dict(data)
            except Exception as e:
                logger.warning(f"Failed to parse MCP_SERVERS_JSON env var: {e}")

        if not json_servers:
            root = Path(workspace_root or os.getcwd()).resolve()
            config_file = root / self.mcp_config_path
            if config_file.exists():
                try:
                    data = json.loads(config_file.read_text(encoding="utf-8"))
                    json_servers = self._parse_servers_dict(data)
                except Exception as e:
                    logger.warning(f"Failed to read or parse MCP config file at {config_file}: {e}")

        if not json_servers:
            import sys
            json_servers = {
                "filesystem": MCPServerConfig(
                    command=sys.executable,
                    args=["-m", "nakama_kun.mcp.servers.filesystem"]
                ),
                "github": MCPServerConfig(
                    command=sys.executable,
                    args=["-m", "nakama_kun.mcp.servers.github"]
                ),
                "postgres": MCPServerConfig(
                    command=sys.executable,
                    args=["-m", "nakama_kun.mcp.servers.postgres"]
                ),
                "browser": MCPServerConfig(
                    command=sys.executable,
                    args=["-m", "nakama_kun.mcp.servers.browser"]
                ),
            }

        # 2. Check for mcp.yaml and overlay/merge
        root = Path(workspace_root or os.getcwd()).resolve()
        yaml_file = root / "mcp.yaml"
        yaml_data: dict[str, Any] = {}
        if yaml_file.exists():
            try:
                import yaml
                content = yaml_file.read_text(encoding="utf-8")
                loaded = yaml.safe_load(content)
                if isinstance(loaded, dict):
                    yaml_data = loaded
            except Exception as e:
                logger.warning(f"Failed to read or parse mcp.yaml: {e}")

        yaml_servers = yaml_data.get("servers") or {}
        if not isinstance(yaml_servers, dict):
            yaml_servers = {}

        # If mcp.yaml exists, we use it to filter and/or configure servers
        final_servers: dict[str, MCPServerConfig] = {}

        # Merge JSON configs using YAML rules
        for name, json_cfg in json_servers.items():
            yaml_cfg = yaml_servers.get(name)
            if yaml_cfg is not None:
                if isinstance(yaml_cfg, dict):
                    enabled = yaml_cfg.get("enabled", True)
                    if not enabled:
                        continue
                    # Override settings if provided in yaml
                    command = yaml_cfg.get("command") or json_cfg.command
                    args = yaml_cfg.get("args") or json_cfg.args
                    env = yaml_cfg.get("env") or json_cfg.env
                    final_servers[name] = MCPServerConfig(
                        command=command,
                        args=args,
                        env=env
                    )
                elif isinstance(yaml_cfg, bool):
                    if not yaml_cfg:
                        continue
                    final_servers[name] = json_cfg
            else:
                final_servers[name] = json_cfg

        # Load any servers defined only in mcp.yaml
        for name, yaml_cfg in yaml_servers.items():
            if name not in final_servers and name not in json_servers:
                if isinstance(yaml_cfg, dict):
                    enabled = yaml_cfg.get("enabled", True)
                    if not enabled:
                        continue
                    command = yaml_cfg.get("command")
                    if command:
                        args = yaml_cfg.get("args") or []
                        env = yaml_cfg.get("env")
                        final_servers[name] = MCPServerConfig(
                            command=command,
                            args=args,
                            env=env
                        )

        return final_servers

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
