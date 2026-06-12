from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from loguru import logger

from nakama_kun.ai.models.message import Message
from nakama_kun.ai.prompts.system_prompt import (
    AGENT_SYSTEM_PROMPT,
)
from nakama_kun.ai.services.chat_service import ChatService
from nakama_kun.ai.services.planner_service import PlannerService
from nakama_kun.orchestration.state import AgentState
from nakama_kun.orchestration.verification import VerificationLayer
from nakama_kun.tools import ToolRegistry, ToolRouter


def make_planner_node(planner_service: PlannerService) -> Callable[[AgentState], Any]:
    """Factory creating the Planner Node.

    Planner node generates or refines the plan based on user goal and reviewer feedback.
    """

    async def planner_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Planner Node starting...")
        goal = state["goal"]
        feedback = state["reviewer_feedback"]
        retry_count = state["retry_count"]

        # If there is feedback, ask the planner to refine the plan
        if feedback:
            logger.info(f"[LangGraph] Refining plan based on feedback (retry {retry_count})...")

            # Extract completed actions (successful tool runs)
            completed_actions = []
            for r in state.get("tool_results", []):
                if r.get("success", False):
                    tool_name = r.get("tool", "")
                    arguments = r.get("arguments", {})
                    completed_actions.append(f"- Tool '{tool_name}' succeeded with args: {json.dumps(arguments)}")

            # Extract previous failures (failed tool runs)
            previous_failures = []
            for r in state.get("tool_results", []):
                if not r.get("success", False):
                    tool_name = r.get("tool", "")
                    arguments = r.get("arguments", {})
                    content = r.get("content", "")
                    content_snippet = content[:200] + "..." if len(content) > 200 else content
                    previous_failures.append(
                        f"- Tool '{tool_name}' failed with args: {json.dumps(arguments)}\n"
                        f"  Output/Error: {content_snippet}"
                    )

            # Extract failed validations from verification report
            failed_validations = []
            report = state.get("verification_report")
            if report:
                # Check created/modified files
                all_artifacts = report.files_created + report.files_modified
                for fa in all_artifacts:
                    if not fa.exists:
                        failed_validations.append(f"- Expected file artifact does not exist: {fa.path}")

                # Check general existence checks
                artifact_paths = {fa.path for fa in all_artifacts}
                for ec in report.existence_checks:
                    if not ec.exists and ec.path not in artifact_paths:
                        failed_validations.append(f"- Referenced file does not exist: {ec.path}")

                # Check command results
                for cr in report.command_results:
                    if not cr.success:
                        if cr.test_summary:
                            failed_validations.append(
                                f"- Test runner command failed: '{cr.cmd}' (Exit code: {cr.exit_code})\n"
                                f"  Tests: {cr.test_summary.get('passed', 0)} passed, {cr.test_summary.get('failed', 0)} failed, "
                                f"{cr.test_summary.get('errors', 0)} errors, {cr.test_summary.get('skipped', 0)} skipped"
                            )
                        else:
                            stdout = cr.stdout_snippet or ""
                            stdout_snippet = stdout[:200] + "..." if len(stdout) > 200 else stdout
                            failed_validations.append(
                                f"- Command failed: '{cr.cmd}' (Exit code: {cr.exit_code})\n"
                                f"  Output:\n{stdout_snippet}"
                            )
            else:
                logger.warning("[LangGraph] Planner: no verification_report in state during retry.")

            prompt_lines = [
                f"Original Goal: {goal}",
                "",
                "We previously attempted this, but the task was not fully successful and requires a revised plan.",
                "",
                "### Reviewer Feedback",
                feedback,
                "",
                "### Completed Actions",
                "\n".join(completed_actions) if completed_actions else "(none)",
                "",
                "### Previous Failures",
                "\n".join(previous_failures) if previous_failures else "(none)",
                "",
                "### Failed Validations",
                "\n".join(failed_validations) if failed_validations else "(none)",
                "",
                "Please update and refine the implementation plan to address the feedback and failures, ensuring that the revised plan avoids the same failures and targets resolving the remaining issues."
            ]
            prompt = "\n".join(prompt_lines)

            # Increment retry count
            retry_count += 1
        else:
            logger.info("[LangGraph] Generating initial implementation plan...")
            prompt = goal

        plan, raw_text = await planner_service.plan(prompt)

        return {
            "plan": plan,
            "status": "executing",
            "retry_count": retry_count,
            "messages": [
                Message(role="assistant", content=f"Planner proposed Plan:\n{raw_text}")
            ],
        }

    return planner_node


def make_executor_node(
    chat_service: ChatService,
    tool_registry: ToolRegistry,
    tool_router: ToolRouter,
) -> Callable[[AgentState], Any]:
    """Factory creating the Executor Node.

    Executor node runs the tool-calling loop based on the current plan and goal.
    """

    async def executor_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Executor Node starting...")
        goal = state["goal"]
        plan = state["plan"]
        plan_desc = plan.goal_summary if plan else "Execute target goal."

        # Setup system prompt with plan context
        system_prompt = (
            f"{AGENT_SYSTEM_PROMPT}\n\n"
            f"### Active Goal\n{goal}\n\n"
            f"### Active Plan\n{plan_desc}\n"
        )
        if plan and plan.ordered_steps:
            steps_str = "\n".join(f"{i}. {s}" for i, s in enumerate(plan.ordered_steps, 1))
            system_prompt += f"\n### Planned Steps:\n{steps_str}\n"

        tool_schemas = tool_registry.all_schemas()

        # Gather messages for LLM context: System message + user goal + current run messages
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Execute this task: {goal}"),
            *state["messages"],
        ]

        logger.info(f"[LangGraph] Calling LLM with {len(messages)} messages...")

        # Run up to 10 rounds of tool calling per executor invocation
        max_rounds = 10
        new_messages: list[Message] = []
        new_tool_results: list[dict[str, Any]] = []

        for round_idx in range(1, max_rounds + 1):
            logger.info(f"[LangGraph] Executor Round {round_idx}/{max_rounds}...")
            response = await chat_service.chat_with_tools(
                messages + new_messages, tool_schemas
            )

            # Check if execution finished
            if response.finish_reason == "stop" or not response.tool_calls:
                assistant_msg = Message(
                    role="assistant", content=response.content or ""
                )
                new_messages.append(assistant_msg)
                logger.info("[LangGraph] Execution completed.")
                break

            # Process tool calls
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
            new_messages.append(assistant_msg)

            for tc in response.tool_calls:
                name = tc.function.get("name", "")
                arguments = tc.function.get("arguments", {})

                logger.info(f"[LangGraph] Dispatching tool {name} with args: {arguments}")
                try:
                    result = await tool_router.dispatch(name, arguments)
                    success = result.success
                    content = result.to_content()
                except Exception as exc:
                    logger.error(f"[LangGraph] Tool execution failed: {exc}")
                    success = False
                    content = f"ERROR: {exc}"

                tool_result_msg = Message(
                    role="tool",
                    content=content,
                    tool_call_id=tc.id,
                    name=name,
                )
                new_messages.append(tool_result_msg)

                new_tool_results.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "success": success,
                        "content": content,
                    }
                )

        return {
            "messages": new_messages,
            "tool_results": new_tool_results,
            "status": "reviewing",
        }

    return executor_node


def make_verifier_node(workspace_root: str | None = None) -> Callable[[AgentState], Any]:
    """Factory creating the Verifier Node.

    Verifier node runs between Executor and Reviewer.  It inspects the real
    workspace — reading written files from disk, extracting command outputs —
    and stores a structured :class:`~nakama_kun.orchestration.verification.VerificationReport`
    in state so the Reviewer has concrete evidence to evaluate.
    """
    layer = VerificationLayer(workspace_root=workspace_root)

    async def verifier_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Verifier Node starting...")
        report = layer.run(state)
        logger.info(f"[LangGraph] Verifier complete: {report.summary}")
        return {
            "verification_report": report,
            "status": "reviewing",
        }

    return verifier_node


def make_reviewer_node(chat_service: ChatService) -> Callable[[AgentState], Any]:
    """Factory creating the Reviewer Node.

    Reviewer node inspects the execution log and decides if the goal was met.
    """

    async def reviewer_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Reviewer Node starting...")
        goal = state["goal"]
        plan = state["plan"]
        verification_report = state.get("verification_report")

        plan_str = plan.goal_summary if plan else "None"

        # Build evidence block from the VerificationReport when available.
        # Fall back to a raw tool-count summary only if the verifier was skipped.
        if verification_report is not None:
            signal = verification_report.evaluate_outcome()
            evidence_block = verification_report.to_reviewer_text()
            signal_header = signal.to_header_text()
        else:
            logger.warning(
                "[LangGraph] Reviewer: no verification_report in state — "
                "falling back to raw tool summary."
            )
            tool_results = state.get("tool_results", [])
            raw_summary = json.dumps(
                [
                    {
                        "tool": r["tool"],
                        "success": r["success"],
                        "output_chars": len(r["content"]),
                    }
                    for r in tool_results
                ]
            )
            evidence_block = (
                f"[No verification report available — raw tool summary:]\n{raw_summary}"
            )
            signal_header = (
                "=== PRE-COMPUTED OUTCOME SIGNAL ===\n"
                "  Recommendation : ⚠️ UNCERTAIN\n"
                "  Reason         : No verification report; falling back to tool summary.\n"
                "=== END OUTCOME SIGNAL ==="
            )

        review_prompt = (
            f"You are a quality control reviewer evaluating whether a task has been completed.\n\n"
            f"Original Goal: {goal}\n"
            f"Proposed Plan: {plan_str}\n\n"
            f"--- DECISION HIERARCHY (follow strictly, in priority order) ---\n\n"
            f"  1. PRIMARY — Artifact Existence (HIGHEST PRIORITY)\n"
            f"     If the requested files/artifacts exist on disk with appropriate content,\n"
            f"     the goal has been achieved. This is sufficient to APPROVE.\n"
            f"     Intermediate tool failures are IRRELEVANT if a fallback produced the artifact.\n\n"
            f"  2. SECONDARY — Test / Command Results\n"
            f"     If tests ran and passed (Exit Code 0), this CONFIRMS the artifacts are correct.\n"
            f"     If tests ran and FAILED (non-zero exit code), this OVERRIDES artifact existence → REJECT.\n\n"
            f"  3. TERTIARY — Tool Execution History (LOWEST PRIORITY)\n"
            f"     Intermediate failures (e.g. a first write_file attempt that failed before a\n"
            f"     successful fallback) are INFORMATIONAL ONLY.\n"
            f"     A ❌ FAIL on an intermediate tool MUST NOT cause rejection if the final\n"
            f"     artifact exists on disk. Do not penalise the use of fallback mechanisms.\n\n"
            f"--- PRE-COMPUTED OUTCOME SIGNAL ---\n"
            f"A deterministic classifier has already evaluated the evidence using the above\n"
            f"hierarchy. Trust this signal strongly:\n\n"
            f"{signal_header}\n\n"
            f"--- FULL EVIDENCE ---\n"
            f"{evidence_block}\n\n"
            f"--- DECISION RULES ---\n"
            f"APPROVE if:\n"
            f"  - Outcome signal is APPROVE, OR\n"
            f"  - Requested artifacts exist on disk AND no tests failed.\n\n"
            f"REJECT only if you have concrete evidence of failure:\n"
            f"  - Required files are explicitly confirmed MISSING from disk, OR\n"
            f"  - A test/validation command exited with a non-zero code, OR\n"
            f"  - File content is clearly wrong or empty for the stated goal.\n\n"
            f"Do NOT reject because:\n"
            f"  - An intermediate tool attempt failed (fallback may have succeeded)\n"
            f"  - The tool history shows any ❌ markers on non-final steps\n"
            f"  - You cannot see something that wasn't required\n\n"
            f"Respond in EXACTLY this format:\n"
            f"If approved:\n"
            f"[APPROVED]\n"
            f"<One paragraph citing the key evidence: which files exist, which tests passed>\n\n"
            f"If rejected:\n"
            f"[REJECTED]\n"
            f"<Bulleted list of CONCRETE evidence of failure — cite specific paths, exit codes, or content>"
        )

        messages = [
            Message(role="system", content="You are a quality control reviewer agent."),
            Message(role="user", content=review_prompt),
        ]

        response = await chat_service.provider.generate(messages)
        content = response.content or ""
        logger.info(f"[LangGraph] Review response received:\n{content}")

        if "[APPROVED]" in content:
            logger.info("[LangGraph] QA Review: APPROVED.")
            return {
                "reviewer_feedback": None,
                "status": "done",
                "messages": [Message(role="assistant", content=f"Reviewer: Approved! {content}")],
            }
        else:
            logger.info("[LangGraph] QA Review: REJECTED.")
            return {
                "reviewer_feedback": content,
                "status": "planning",
                "messages": [Message(role="assistant", content=f"Reviewer: Rejected. {content}")],
            }

    return reviewer_node


def make_final_response_node(chat_service: ChatService) -> Callable[[AgentState], Any]:
    """Factory creating the Final Response Node.

    Synthesizes the plan execution and outputs a friendly markdown summary.
    """

    async def final_response_node(state: AgentState) -> dict[str, Any]:
        logger.info("[LangGraph] Final Response Node starting...")
        goal = state["goal"]
        plan = state["plan"]
        tool_results = state["tool_results"]

        summary_prompt = (
            f"Synthesize a final report summarizing the agent's work.\n"
            f"User Goal: {goal}\n"
            f"Plan Proposed: {plan.goal_summary if plan else 'None'}\n"
            f"Tool Executions: {len(tool_results)} runs.\n\n"
            f"Create a beautiful markdown summary reporting what actions were completed, "
            f"what files were modified or created, and confirming task completion."
        )

        messages = [
            Message(role="system", content="You are a helpful assistant reporting task results."),
            Message(role="user", content=summary_prompt),
        ]

        response = await chat_service.provider.generate(messages)
        content = response.content or ""

        return {"final_response": content, "status": "done"}

    return final_response_node
