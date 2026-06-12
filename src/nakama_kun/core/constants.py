"""
core/constants.py — Immutable application-wide constants for nakama_kun.

All magic strings, version tags, phase identifiers, and colour tokens live
here.  Importing from a single source of truth prevents typos and makes
renaming trivial.

Phase 3+: add AI model IDs, endpoint URLs, timeout values, etc.
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Phase identifiers
# ---------------------------------------------------------------------------

class AppPhase(StrEnum):
    """Human-readable labels for each nakama_kun development phase."""

    PHASE_1 = "Phase 1 · Core CLI Skeleton"
    PHASE_2 = "Phase 2 · Multi-Mode Architecture"
    PHASE_3 = "Phase 3 · AI Integration"
    PHASE_4 = "Phase 4 · Tool Calling"          # current
    PHASE_5 = "Phase 5 · Planning Agent"        # future
    PHASE_6 = "Phase 6 · Workspace Awareness"   # future
    PHASE_7 = "Phase 7 · Telegram Bot"          # future


# ---------------------------------------------------------------------------
# Application metadata
# ---------------------------------------------------------------------------

APP_NAME: str = "nakama_kun"
APP_VERSION: str = "0.4.0"
APP_DESCRIPTION: str = "An OpenClaw-style AI Agent CLI — your nakama in the terminal."

CURRENT_PHASE: AppPhase = AppPhase.PHASE_5



# ---------------------------------------------------------------------------
# UI / Rich colour tokens
# (centralised so every panel and menu uses the same palette)
# ---------------------------------------------------------------------------

class Colours:
    """Terminal colour palette for the nakama_kun Rich UI."""

    PRIMARY: str = "bright_cyan"
    SECONDARY: str = "bright_magenta"
    SUCCESS: str = "bright_green"
    WARNING: str = "yellow"
    ERROR: str = "bright_red"
    MUTED: str = "dim white"
    ACCENT: str = "bright_white"

    # Mode-specific
    CLI: str = "green"
    TELEGRAM: str = "blue"
    AGENT: str = "bright_cyan"
    PLAN: str = "bright_yellow"
    ASK: str = "bright_magenta"


# ---------------------------------------------------------------------------
# Navigation sentinel — returned by modes to signal router action
# ---------------------------------------------------------------------------

class NavSignal(StrEnum):
    """
    Signals a mode can return to the Router to control navigation.

    CONTINUE  — stay in the current context and loop.
    BACK      — pop back to the parent menu.
    EXIT      — terminate the application gracefully.

    Future signals (Phase 3+):
        SWITCH_MODE — jump to a different top-level mode.
        RESTART     — re-initialise the session.
    """

    CONTINUE = "continue"
    BACK = "back"
    EXIT = "exit"
