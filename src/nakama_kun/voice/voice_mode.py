from __future__ import annotations

import asyncio
import re
from typing import Any

import questionary
from loguru import logger
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from nakama_kun.ai.models.message import Message
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.config.voice import VoiceSettings
from nakama_kun.core.constants import APP_VERSION, NavSignal
from nakama_kun.modes.agent_mode import AgentMode
from nakama_kun.modes.ask_mode import AskMode
from nakama_kun.modes.base import BaseMode
from nakama_kun.modes.plan_mode import PlanMode
from nakama_kun.ui.console import console
from nakama_kun.ui.menus import _MENU_STYLE
from nakama_kun.voice.elevenlabs_tts import ElevenLabsTTS
from nakama_kun.voice.player import AudioPlayer
from nakama_kun.voice.recorder import AudioRecorder
from nakama_kun.voice.whisper_stt import WhisperSTT


class VoiceMode(BaseMode):
    """Voice Mode — Hands-free voice conversation routing to Ask, Plan, or Agent workflows."""

    name: str = "Voice Mode"

    def __init__(
        self,
        chat_service: ChatService,
        agent_mode: AgentMode,
        plan_mode: PlanMode,
        ask_mode: AskMode,
        settings: VoiceSettings | None = None,
    ) -> None:
        self._chat_service = chat_service
        self._agent_mode = agent_mode
        self._plan_mode = plan_mode
        self._ask = ask_mode
        self.settings = settings or VoiceSettings()

        self._stt = WhisperSTT(self.settings)
        self._tts = ElevenLabsTTS(self.settings)
        self._recorder = AudioRecorder()
        self._player = AudioPlayer()
        self._planner_service = PlannerService(self._chat_service)

    def run(self) -> NavSignal:
        try:
            return asyncio.run(self._run_async())
        except KeyboardInterrupt:
            console.print("\n[yellow]Returning to menu...[/yellow]")
            return NavSignal.BACK

    async def _run_async(self) -> NavSignal:
        while True:
            console.print()
            console.print(
                Panel(
                    Text(
                        "nakama_kun Voice Mode\n"
                        "Select a workflow to run via speech.",
                        style="bold magenta",
                        justify="center",
                    ),
                    border_style="magenta",
                    title="Voice Mode",
                    subtitle=f"v{APP_VERSION}",
                )
            )

            try:
                choice = await questionary.select(
                    "Voice target workflow:",
                    choices=[
                        "Agent Mode (Voice)",
                        "Plan Mode (Voice)",
                        "Ask Mode (Voice)",
                        "Back",
                    ],
                    style=_MENU_STYLE,
                ).ask_async()
            except (KeyboardInterrupt, EOFError):
                return NavSignal.BACK

            if choice is None or choice == "Back":
                return NavSignal.BACK

            if choice == "Agent Mode (Voice)":
                await self._voice_loop("agent")
            elif choice == "Plan Mode (Voice)":
                await self._voice_loop("plan")
            elif choice == "Ask Mode (Voice)":
                await self._voice_loop("ask")

    async def _voice_loop(self, target: str) -> None:
        console.print(
            f"\n[bold green]Voice loop started for {target.capitalize()} Mode. Speak now...[/bold green]"
        )

        history: list[Message] = []
        tool_schemas: list[dict[str, Any]] = []
        if target == "agent":
            tool_schemas = self._agent_mode._registry.all_schemas()

        while True:
            try:
                # 1. Record User Audio
                try:
                    audio_file = self._recorder.record(
                        duration=15.0,
                        device_index=self.settings.voice_audio_device_index,
                    )
                except ImportError as e:
                    console.print(f"\n[bold red]{e}[/bold red]\n")
                    break
                except Exception as e:
                    console.print(f"\n[bold red]Recording failed: {e}[/bold red]\n")
                    break

                # 2. Transcribe Audio
                console.print("[italic dim]Transcribing speech...[/italic dim]")
                try:
                    user_msg = await self._stt.transcribe(audio_file)
                except Exception as e:
                    console.print(f"\n[bold red]Transcription failed: {e}[/bold red]\n")
                    self._cleanup_file(audio_file)
                    break

                self._cleanup_file(audio_file)

                user_msg = user_msg.strip()
                if not user_msg:
                    console.print("[yellow]No speech detected. Try again.[/yellow]")
                    continue

                console.print(f"\n[bold green]You (Spoken):[/bold green] {user_msg}")

                if user_msg.lower() in ("exit", "quit", "back"):
                    console.print("[yellow]Exiting Voice loop...[/yellow]")
                    break

                # 3. Process & Route
                if target == "ask":
                    from nakama_kun.ai.prompts.system_prompt import ASK_SYSTEM_PROMPT
                    from nakama_kun.rag import get_retriever
                    from nakama_kun.workspace.context import WorkspaceContextBuilder
                    try:
                        workspace_context = WorkspaceContextBuilder().build_summary()
                        system_prompt = f"{ASK_SYSTEM_PROMPT}\n\n{workspace_context}"

                        retriever = get_retriever()
                        if retriever is not None:
                            rag_context = retriever.retrieve_formatted_context(user_msg)
                            if rag_context:
                                system_prompt += f"\n\n{rag_context}"

                        self._chat_service.system_prompt = system_prompt
                    except Exception:
                        self._chat_service.system_prompt = ASK_SYSTEM_PROMPT

                    console.print("\n[bold magenta]nakama_kun:[/bold magenta]")
                    response_text = ""
                    with Live(Markdown(""), auto_refresh=False) as live:
                        async for token in self._chat_service.chat_stream(user_msg):
                            response_text += token
                            live.update(Markdown(response_text))
                            live.refresh()
                    console.print()

                    await self._speak_text(response_text)

                elif target == "plan":
                    console.print("\n[bold yellow]nakama_kun Planner:[/bold yellow]")
                    console.print("[italic dim]Planning...[/italic dim]")
                    plan, raw_text = await self._planner_service.plan(user_msg)

                    if plan is not None:
                        self._plan_mode._render_plan(plan)
                        spoken_summary = (
                            f"I have created an implementation plan. Goal summary: {plan.goal_summary}. "
                        )
                        if plan.ordered_steps:
                            spoken_summary += f"There are {len(plan.ordered_steps)} steps. "
                            spoken_summary += f"Step 1: {plan.ordered_steps[0]}"
                        await self._speak_text(spoken_summary)
                    else:
                        self._plan_mode._render_unstructured(raw_text)
                        await self._speak_text(raw_text)

                elif target == "agent":
                    console.print("\n[bold cyan]nakama_kun Agent Mode:[/bold cyan]")
                    final_answer = await self._agent_mode._agent_loop(
                        user_msg, history, tool_schemas
                    )
                    if final_answer:
                        console.print(f"\n[bold cyan]Final Answer:[/bold cyan] {final_answer}")
                        history.append(Message(role="assistant", content=final_answer))
                        await self._speak_text(final_answer)

            except KeyboardInterrupt:
                console.print("\n[yellow]Voice loop interrupted.[/yellow]")
                break
            except Exception as e:
                console.print(f"\n[bold red]Error in Voice loop: {e}[/bold red]\n")
                break

    async def _speak_text(self, text: str) -> None:
        sentence_endings = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*')
        sentences = [s.strip() for s in sentence_endings.split(text) if s.strip()]

        for sentence in sentences:
            if not sentence:
                continue
            console.print(f"[italic dim]Speaking: {sentence}...[/italic dim]")
            try:
                audio_data = await self._tts.synthesize(sentence)
                self._player.play(audio_data)
            except Exception as e:
                logger.warning(
                    f"Voice playback/synthesis failed for sentence '{sentence}': {e}"
                )
                console.print(
                    f"[bold yellow](Speech unavailable: {sentence})[/bold yellow]"
                )

    def _cleanup_file(self, file_path: str) -> None:
        try:
            import os
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
