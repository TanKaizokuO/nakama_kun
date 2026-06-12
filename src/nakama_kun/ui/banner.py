"""
banner.py — ASCII art startup banner for nakama_kun.

Uses PyFiglet to generate large text art and Rich to style and render it
inside a framed panel. The banner is the first thing the user sees on
startup, so it must be visually striking.
"""

import pyfiglet
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Shared console instance — keeps all UI output consistent
console = Console()


def _build_banner_text(app_name: str, font: str = "slant") -> Text:
    """
    Render *app_name* as large ASCII art using PyFiglet.

    Args:
        app_name: The name to render (e.g. "nakama_kun").
        font:     PyFiglet font name.  Falls back to 'standard' on failure.

    Returns:
        A Rich :class:`~rich.text.Text` object with gradient colouring.
    """
    try:
        raw: str = pyfiglet.figlet_format(app_name, font=font)
    except pyfiglet.FontNotFound:
        raw = pyfiglet.figlet_format(app_name, font="standard")

    # Apply a cyan → magenta gradient line-by-line for visual depth
    styled = Text()
    colours = [
        "bright_cyan",
        "cyan",
        "bright_magenta",
        "magenta",
        "bright_cyan",
        "cyan",
    ]
    for i, line in enumerate(raw.splitlines()):
        colour = colours[i % len(colours)]
        styled.append(line + "\n", style=f"bold {colour}")

    return styled


def display_banner(
    app_name: str = "nakama kun",
    subtitle: str = "Phase 1 · OpenClaw-style AI Agent CLI",
    version: str = "v0.1.0",
) -> None:
    """
    Print the startup banner to the terminal.

    The banner consists of:
    - Large PyFiglet ASCII art (gradient coloured via Rich)
    - A subtitle line
    - A version badge

    Args:
        app_name:  Name passed to PyFiglet.
        subtitle:  Descriptive tagline shown beneath the art.
        version:   Version string shown in the footer.
    """
    banner_text = _build_banner_text(app_name)

    # Subtitle line
    sub = Text(subtitle, style="italic dim white")
    ver = Text(f"  {version}", style="bold green")

    # Compose into a Rich Panel with a themed border
    content = Align.center(banner_text)
    panel = Panel(
        content,
        subtitle=Text.assemble(sub, "  ", ver),
        border_style="bright_cyan",
        padding=(0, 2),
    )

    console.print()
    console.print(panel)
    console.print()
