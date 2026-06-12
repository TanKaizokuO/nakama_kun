"""
modes/__init__.py — Mode system for nakama_kun.

Every runnable mode in the application inherits from :class:`BaseMode`.
Import from here for a stable public API:

    from nakama_kun.modes import BaseMode, AgentMode, PlanMode, AskMode
    from nakama_kun.modes import CLIMode, TelegramMode

Design contract
---------------
``BaseMode.run()`` returns a :class:`~nakama_kun.core.constants.NavSignal`
telling the Router what to do next:

    NavSignal.BACK     → return to the parent menu
    NavSignal.EXIT     → terminate the application
    NavSignal.CONTINUE → stay in the current context (loop)
"""

from nakama_kun.modes.agent_mode import AgentMode
from nakama_kun.modes.ask_mode import AskMode
from nakama_kun.modes.base import BaseMode
from nakama_kun.modes.cli_mode import CLIMode
from nakama_kun.modes.plan_mode import PlanMode
from nakama_kun.modes.telegram_mode import TelegramMode

__all__ = [
    "BaseMode",
    "AgentMode",
    "PlanMode",
    "AskMode",
    "CLIMode",
    "TelegramMode",
]
