"""
modes/base.py — Abstract base class for all nakama_kun modes.

Every mode in the application is a concrete subclass of :class:`BaseMode`.
The interface is intentionally minimal: one ``run()`` method that returns
a :class:`~nakama_kun.core.constants.NavSignal`.

SOLID compliance
----------------
* **S** — single responsibility: each subclass owns exactly one mode's logic.
* **O** — open/closed: add new modes by subclassing, not editing the base.
* **L** — Liskov: every subclass can be used wherever BaseMode is expected.
* **I** — interface segregation: ``run()`` is the only required contract.
* **D** — dependency inversion: modes depend on NavSignal (abstraction),
          not on concrete Router internals.

Phase 3+ extension points
--------------------------
Subclasses can override ``setup()`` / ``teardown()`` hooks once they appear
here.  The Router will call them before/after ``run()`` automatically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from nakama_kun.core.constants import NavSignal


class BaseMode(ABC):
    """
    Abstract base class for all application modes.

    Subclasses must implement :meth:`run` and should document their own
    Phase extension points in their module docstrings.

    Attributes:
        name: Human-readable display name used in panels and logs.
    """

    #: Override in subclasses to provide a human-readable label.
    name: str = "Unnamed Mode"

    @abstractmethod
    def run(self) -> NavSignal:
        """
        Execute this mode's primary loop and return a navigation signal.

        Returns:
            :attr:`~nakama_kun.core.constants.NavSignal.BACK`     — return to
                the caller's menu.
            :attr:`~nakama_kun.core.constants.NavSignal.EXIT`     — exit the
                application.
            :attr:`~nakama_kun.core.constants.NavSignal.CONTINUE` — loop
                within the caller (rarely used at leaf modes).
        """
        ...

    # ------------------------------------------------------------------
    # Phase 3+ lifecycle hooks (no-ops until overridden)
    # ------------------------------------------------------------------

    def setup(self) -> None:  # noqa: B027
        """
        Called by the Router before ``run()``.

        Phase 3: sub-classes can initialise AI clients, load memory, etc.
        """

    def teardown(self) -> None:  # noqa: B027
        """
        Called by the Router after ``run()`` returns.

        Phase 3: sub-classes can flush memory, close connections, etc.
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
