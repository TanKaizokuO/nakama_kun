from __future__ import annotations

import time
from typing import Any
from nakama_kun.agents.models import AgentMessage


class AgentCommunicationLayer:
    """Brokers and tracks structured AgentMessage communication between agents."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state
        if "agent_messages" not in state:
            state["agent_messages"] = []

    def send_message(self, message: AgentMessage) -> None:
        self._state["agent_messages"].append(message)

    def get_messages(
        self, receiver: str | None = None, sender: str | None = None
    ) -> list[AgentMessage]:
        msgs = self._state["agent_messages"]
        # Convert dict to AgentMessage objects if they were serialized
        msg_objs = []
        for m in msgs:
            if isinstance(m, dict):
                msg_objs.append(AgentMessage.model_validate(m))
            else:
                msg_objs.append(m)

        if receiver:
            msg_objs = [m for m in msg_objs if m.receiver == receiver]
        if sender:
            msg_objs = [m for m in msg_objs if m.sender == sender]
        return msg_objs

    def request_information(self, sender: str, receiver: str, info_query: str) -> None:
        msg = AgentMessage(
            sender=sender,
            receiver=receiver,
            message_type="request_information",
            payload={"query": info_query},
            timestamp=time.time(),
        )
        self.send_message(msg)

    def share_findings(self, sender: str, receiver: str, findings: dict[str, Any]) -> None:
        msg = AgentMessage(
            sender=sender,
            receiver=receiver,
            message_type="share_findings",
            payload=findings,
            timestamp=time.time(),
        )
        self.send_message(msg)

    def submit_recommendations(
        self, sender: str, receiver: str, recommendations: list[str]
    ) -> None:
        msg = AgentMessage(
            sender=sender,
            receiver=receiver,
            message_type="submit_recommendations",
            payload={"recommendations": recommendations},
            timestamp=time.time(),
        )
        self.send_message(msg)
