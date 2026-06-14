from __future__ import annotations

from typing import Any


class AgentCapability:
    """Tracks capability profile of a specialized agent in Nakama-kun."""

    def __init__(
        self,
        name: str,
        role: str,
        capabilities: list[str],
        tool_access: list[str],
        availability: bool = True,
    ) -> None:
        self.name = name
        self.role = role
        self.capabilities = capabilities
        self.tool_access = tool_access
        self.availability = availability

    def to_dict(self) -> dict[str, Any]:
        """Convert capability to serializable dictionary."""
        return {
            "name": self.name,
            "role": self.role,
            "capabilities": self.capabilities,
            "tool_access": self.tool_access,
            "availability": self.availability,
        }


class AgentCapabilityRegistry:
    """Registry managing available agent capabilities and tool access details."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentCapability] = {}
        self._register_defaults()

    def register_agent(
        self,
        name: str,
        role: str,
        capabilities: list[str],
        tool_access: list[str],
        availability: bool = True,
    ) -> None:
        """Register or update agent capabilities profile."""
        self._agents[name] = AgentCapability(
            name=name,
            role=role,
            capabilities=capabilities,
            tool_access=tool_access,
            availability=availability,
        )

    def get_agent(self, name: str) -> AgentCapability | None:
        """Retrieve agent capability profile by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[AgentCapability]:
        """List all registered agent capability profiles."""
        return list(self._agents.values())

    def _register_defaults(self) -> None:
        """Pre-populate the registry with standard specialized agents."""
        self.register_agent(
            name="PlannerAgent",
            role="planner",
            capabilities=["task decomposition", "planning", "strategy formulation"],
            tool_access=[],
        )
        self.register_agent(
            name="RetrieverAgent",
            role="retriever",
            capabilities=["codebase search", "RAG retrieval", "dependency analysis"],
            tool_access=["read_file", "list_directory", "search_files"],
        )
        self.register_agent(
            name="CoderAgent",
            role="coder",
            capabilities=["code generation", "implementation", "refactoring"],
            tool_access=["read_file", "write_file", "run_command"],
        )
        self.register_agent(
            name="TestAgent",
            role="tester",
            capabilities=["test creation", "test execution", "test repair"],
            tool_access=["read_file", "write_file", "run_command"],
        )
        self.register_agent(
            name="SecurityAgent",
            role="security",
            capabilities=["secret detection", "unsafe command blocking", "dependency risk check", "security audit"],
            tool_access=["read_file"],
        )
        self.register_agent(
            name="VerifierAgent",
            role="verifier",
            capabilities=["workspace verification", "evidence compilation"],
            tool_access=["read_file", "run_command"],
        )
        self.register_agent(
            name="ReviewerAgent",
            role="reviewer",
            capabilities=["QA review", "correctness evaluation", "completion check"],
            tool_access=[],
        )
