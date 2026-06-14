from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class MCPCallMetric:
    server: str
    tool: str
    latency_ms: float
    success: bool
    error: str | None = None


class MCPTelemetry:
    """Tracks performance and success metrics of MCP tool executions."""

    _instance: MCPTelemetry | None = None

    @classmethod
    def get_instance(cls) -> MCPTelemetry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.metrics: list[MCPCallMetric] = []

    def reset(self) -> None:
        """Clear all metrics."""
        self.metrics.clear()

    def record_call(
        self, server: str, tool: str, start_time: float, success: bool, error: str | None = None
    ) -> None:
        latency_ms = (time.time() - start_time) * 1000.0
        metric = MCPCallMetric(
            server=server,
            tool=tool,
            latency_ms=latency_ms,
            success=success,
            error=error
        )
        self.metrics.append(metric)

    def get_stats(self) -> dict[str, Any]:
        """Computes summary statistics for tool executions."""
        total_calls = len(self.metrics)
        success_calls = sum(1 for m in self.metrics if m.success)
        failed_calls = total_calls - success_calls
        success_rate = (success_calls / total_calls) if total_calls > 0 else 0.0

        server_stats: dict[str, dict[str, Any]] = {}
        for m in self.metrics:
            s_name = m.server
            if s_name not in server_stats:
                server_stats[s_name] = {"calls": 0, "success": 0, "latencies": []}
            server_stats[s_name]["calls"] += 1
            if m.success:
                server_stats[s_name]["success"] += 1
            server_stats[s_name]["latencies"].append(m.latency_ms)

        formatted_servers = {}
        for s_name, data in server_stats.items():
            s_calls = data["calls"]
            s_success = data["success"]
            avg_latency = sum(data["latencies"]) / s_calls if s_calls > 0 else 0.0
            formatted_servers[s_name] = {
                "calls": s_calls,
                "success_rate": s_success / s_calls if s_calls > 0 else 0.0,
                "avg_latency_ms": avg_latency,
            }

        return {
            "total_calls": total_calls,
            "success_rate": success_rate,
            "failures": failed_calls,
            "servers": formatted_servers,
        }
