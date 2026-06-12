"""
core/router.py — Central navigation router for nakama_kun.

The Router owns all mode-to-mode transitions.  Each top-level mode is
registered at construction time; the router then calls ``mode.run()`` and
inspects the returned :class:`~nakama_kun.core.constants.NavSignal` to decide
what happens next.

Design decisions
----------------
* **No global state** — the router is constructed once in ``wakeup.py`` and
  passed explicitly where needed.
* **Open/Closed** — registering a new mode only requires one line in the
  caller, not a change to the router itself.
* **NavSignal protocol** — modes communicate intent (back / exit / continue)
  via a typed enum, not raw booleans or strings.

Phase 3+ extension points
--------------------------
* ``Router.register_middleware()`` — for telemetry, logging, auth guards.
* ``Router.set_context()`` — to inject AI context into every mode invocation.
* ``Router.history`` — already wired; Phase 5 planner can use breadcrumbs.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from rich.console import Console

from nakama_kun.core.constants import NavSignal

if TYPE_CHECKING:
    from nakama_kun.modes import BaseMode

console = Console()


class Router:
    """
    Central navigation router.

    Attributes:
        _registry: Maps mode name → BaseMode instance.
        history:   Ordered list of mode names visited (breadcrumb trail).
                   Phase 5 planner will use this to build task context.
    """

    def __init__(self) -> None:
        self._registry: dict[str, BaseMode] = {}
        self.history: list[str] = []

        # Phase 3 extension point: middleware hooks list
        # self._middleware: list[MiddlewareFn] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, mode: BaseMode) -> None:
        """
        Register a mode under a symbolic name.

        Args:
            name: Unique identifier (e.g. ``"cli"``, ``"telegram"``).
            mode: A :class:`~nakama_kun.modes.BaseMode` instance.

        Raises:
            ValueError: If *name* is already registered (prevents silent
                overwrite which would be hard to debug).
        """
        if name in self._registry:
            raise ValueError(
                f"Router: mode '{name}' is already registered. "
                "Use a unique name or deregister the existing one first."
            )
        self._registry[name] = mode

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def launch(self, name: str) -> NavSignal:
        """
        Launch a registered mode and return the navigation signal it emits.

        The breadcrumb history is updated before the mode runs so that the
        mode itself can inspect the stack via ``router.history`` if needed.

        Args:
            name: The registered name of the mode to launch.

        Returns:
            The :class:`~nakama_kun.core.constants.NavSignal` the mode emitted.

        Raises:
            KeyError: If *name* was not registered.
        """
        if name not in self._registry:
            raise KeyError(
                f"Router: no mode registered as '{name}'. "
                f"Available: {list(self._registry)}"
            )

        self.history.append(name)
        mode = self._registry[name]

        # Phase 3 extension point: run middleware before/after mode
        # for mw in self._middleware:
        #     mw.before(name, mode)

        signal = mode.run()

        # Phase 3 extension point:
        # for mw in self._middleware:
        #     mw.after(name, mode, signal)

        return signal

    def back(self) -> str | None:
        """
        Pop the current mode from the breadcrumb stack.

        Returns:
            The name of the mode we returned to, or ``None`` if the stack
            is empty (i.e. we are already at the root).
        """
        if self.history:
            self.history.pop()
        return self.history[-1] if self.history else None

    # ------------------------------------------------------------------
    # Graceful exit
    # ------------------------------------------------------------------

    def exit(self, message: str = "Goodbye!") -> None:
        """
        Terminate the application cleanly.

        Args:
            message: Final farewell message (overridable for testing).
        """
        console.print()
        console.print(f"[bold bright_magenta]{message}[/bold bright_magenta]")
        console.print()
        sys.exit(0)
