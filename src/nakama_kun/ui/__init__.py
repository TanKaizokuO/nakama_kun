"""
UI package for nakama_kun — Phase 2.

Exposes all terminal UI components:
  - banner      : ASCII startup art
  - menus       : top-level and sub-menus with typed enums
  - console     : shared Rich Console singleton
"""

from nakama_kun.ui.banner import display_banner
from nakama_kun.ui.console import console
from nakama_kun.ui.menus import (
    CLIMenuChoice,
    MainMenuChoice,
    show_cli_menu,
    show_main_menu,
)

__all__ = [
    "display_banner",
    "console",
    "MainMenuChoice",
    "CLIMenuChoice",
    "show_main_menu",
    "show_cli_menu",
]
