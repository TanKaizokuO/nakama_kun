from __future__ import annotations

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from nakama_kun.safety.models import ApprovalProvider, FileChangeProposal


class TerminalApprovalProvider(ApprovalProvider):
    """Renders a unified diff in the terminal and prompts the user for y/n confirmation."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def request_approval(self, proposal: FileChangeProposal) -> bool:
        """Draws a beautiful diff and prompts the user to approve the change."""
        self.console.print()
        
        # Determine title details based on change type
        title_str = (
            f"[bold yellow]⚠️ Proposed Change: {proposal.change_type.upper()} "
            f"'{proposal.file_path.name}'[/bold yellow]"
        )

        # Highlight the diff
        diff_syntax = Syntax(
            proposal.diff_text,
            "diff",
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
        )

        self.console.print(
            Panel(
                diff_syntax,
                title=title_str,
                subtitle=f"Path: {proposal.file_path}",
                border_style="yellow",
                padding=(1, 2),
            )
        )

        # Prompt for approval using questionary confirm
        try:
            approved = questionary.confirm(
                "Do you approve applying this change?", default=False
            ).ask()
        except (KeyboardInterrupt, EOFError):
            approved = False

        if not approved:
            self.console.print("[bold red]✗ Change rejected by user.[/bold red]\n")
        else:
            self.console.print("[bold green]✓ Change approved and applied.[/bold green]\n")

        return bool(approved)
