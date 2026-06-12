"""
core/__init__.py — nakama_kun core infrastructure package.

Exports the central router and shared constants so every sub-package
can import from a single stable location:

    from nakama_kun.core import router, constants

Phase 3+ will add:
    from nakama_kun.core.ai import LLMClient
"""

from nakama_kun.core.constants import AppPhase
from nakama_kun.core.router import Router

__all__ = ["Router", "AppPhase"]
