"""
cli/ — Command-line interface sub-package for nakama_kun (Phase 2).

``commands.py`` is the stable public surface: import Typer commands from
there, not from the implementation modules directly.

    from nakama_kun.cli.commands import wakeup_command
"""

from nakama_kun.cli.commands import wakeup_command

__all__ = ["wakeup_command"]
