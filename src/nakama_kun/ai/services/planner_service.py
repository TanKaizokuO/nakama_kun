from nakama_kun.ai.models.message import Message
from nakama_kun.ai.models.plan import Plan, parse_plan
from nakama_kun.ai.prompts.system_prompt import PLANNER_SYSTEM_PROMPT
from nakama_kun.ai.services.chat_service import ChatService


class PlannerService:
    """Service dedicated to task planning and decomposition.

    Maintains a conversation history for planning context and leverages the
    underlying LLM provider to construct plans.
    """

    def __init__(self, chat_service: ChatService) -> None:
        self._chat_service = chat_service
        self.history: list[Message] = []

    async def plan(self, prompt: str) -> tuple[Plan | None, str]:
        """Send a planning query to the AI provider.

        Maintains history of previous queries and answers in this planning session.
        Returns a tuple of (parsed Plan object or None, raw response text).
        """
        from nakama_kun.rag import get_retriever
        from nakama_kun.workspace.context import WorkspaceContextBuilder
        try:
            workspace_context = WorkspaceContextBuilder().build_summary(prompt)
            full_system_prompt = f"{PLANNER_SYSTEM_PROMPT}\n\n{workspace_context}"

            # Retrieve matching codebase chunks for planning prompt
            retriever = get_retriever()
            if retriever is not None:
                rag_context = retriever.retrieve_formatted_context(prompt)
                if rag_context:
                    full_system_prompt += f"\n\n{rag_context}"
        except Exception:
            full_system_prompt = PLANNER_SYSTEM_PROMPT

        system_msg = Message(role="system", content=full_system_prompt)
        user_msg = Message(role="user", content=prompt)

        # Assemble full prompt history
        messages = [system_msg, *self.history, user_msg]

        # Call the underlying LLM provider
        response = await self._chat_service.provider.generate(messages)

        # Update persistent conversation history
        self.history.append(user_msg)
        self.history.append(Message(role="assistant", content=response.content or ""))

        raw_text = response.content or ""
        plan = parse_plan(raw_text)

        return plan, raw_text
