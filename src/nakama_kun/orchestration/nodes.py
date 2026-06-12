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
from nakama_kun.orchestration.evidence import build_evidence_store
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
        evidence_store = build_evidence_store(state, report, workspace_root)
        return {
            "verification_report": report,
            "evidence_store": evidence_store,
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
        evidence_store = state.get("evidence_store")

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

        evidence_store_block = ""
        if evidence_store:
            lines = [
                "=== EVIDENCE STORE (PRESERVED HISTORICAL EVIDENCE) ===",
            ]
            lines.append(f"🛠️ PRESERVED TOOL OUTPUTS ({len(evidence_store.tool_outputs)}):")
            for to in evidence_store.tool_outputs:
                lines.append(f"  - Tool: {to.tool} (Success: {to.success})")
                lines.append(f"    Args: {json.dumps(to.arguments)}")
                snippet = to.output[:1000] + "..." if len(to.output) > 1000 else to.output
                lines.append(f"    Output:\n{snippet}")

            lines.append(f"\n📄 PRESERVED FILE VALIDATIONS ({len(evidence_store.file_validations)}):")
            for fv in evidence_store.file_validations:
                status = "EXISTS" if fv.exists else "MISSING"
                lines.append(f"  - Path: {fv.path} ({status}, Source: {fv.source})")
                if fv.content:
                    snippet = fv.content[:1000] + "..." if len(fv.content) > 1000 else fv.content
                    lines.append(f"    Content:\n{snippet}")

            lines.append(f"\n💻 PRESERVED COMMAND OUTPUTS ({len(evidence_store.command_outputs)}):")
            for co in evidence_store.command_outputs:
                status = "PASS" if co.success else "FAIL"
                lines.append(f"  - Command: {co.cmd} ({status}, Exit code: {co.exit_code})")
                snippet = co.output[:1000] + "..." if len(co.output) > 1000 else co.output
                lines.append(f"    Output:\n{snippet}")

            lines.append(f"\n🧪 PRESERVED TEST RESULTS ({len(evidence_store.test_outputs)}):")
            for tst in evidence_store.test_outputs:
                status = "PASS" if tst.success else "FAIL"
                lines.append(f"  - Command: {tst.cmd} ({status})")
                lines.append(f"    Tests: {tst.passed} passed, {tst.failed} failed, {tst.errors} errors, {tst.skipped} skipped")

            lines.append("=== END EVIDENCE STORE ===")
            evidence_store_block = "\n".join(lines)

        review_prompt = (
            f"You are a quality control reviewer evaluating whether a task has been completed.\n\n"
            f"Original Goal: {goal}\n"
            f"Proposed Plan: {plan_str}\n\n"
            f"--- DECISION HIERARCHY (follow strictly, in priority order) ---\n\n"
            f"  1. PRIMARY — Artifact Existence (HIGHEST PRIORITY)\n"
            f"     If the requested files/artifacts exist on disk with appropriate content,\n"
            f"     the goal has been achieved. This is sufficient to APPROVE.\n"
            f"     Intermediate tool failures are IRRELEVANT if a fallback produced the artifact.\n"
            f"     If a file is physically missing from the final disk state but is recorded in the\n"
            f"     Evidence Store as successfully read or verified during execution (source: tool_read or tool_write),\n"
            f"     and it was not a required final output artifact, do NOT reject the task based on that file being missing.\n\n"
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
        )
        if evidence_store_block:
            review_prompt += (
                f"--- EVIDENCE STORE (HISTORICAL EXECUTION EVIDENCE) ---\n"
                f"{evidence_store_block}\n\n"
            )
        review_prompt += (
            "--- DECISION RULES ---\n"
            "APPROVE if:\n"
            "  - Outcome signal is APPROVE, OR\n"
            "  - Requested artifacts exist on disk AND no tests failed,\n"
            "  - OR a file is physically missing but the Evidence Store validates it was successfully read/written during tool run.\n\n"
            "REJECT only if you have concrete evidence of failure:\n"
            "  - Required files are explicitly confirmed MISSING from disk and have no successful read/write record in the Evidence Store, OR\n"
            "  - A test/validation command exited with a non-zero code, OR\n"
            "  - File content is clearly wrong or empty for the stated goal.\n\n"
            "Do NOT reject because:\n"
            "  - An intermediate tool attempt failed (fallback may have succeeded)\n"
            "  - The tool history shows any ❌ markers on non-final steps\n"
            "  - You cannot see something that wasn't required\n\n"
            "Respond in EXACTLY this format:\n"
            "If approved:\n"
            "[APPROVED]\n"
            "<One paragraph citing the key evidence: which files exist, which tests passed>\n\n"
            "If rejected:\n"
            "[REJECTED]\n"
            "<Bulleted list of CONCRETE evidence of failure — cite specific paths, exit codes, or content>"
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
        tool_results = state.get("tool_results", [])
        verification_report = state.get("verification_report")

        # Extract structured metrics
        files_created: list[str] = []
        files_modified: list[str] = []
        workspace_snapshot: list[str] = []
        total_passed = 0
        total_failed = 0
        total_errors = 0
        total_skipped = 0
        has_tests = False

        if verification_report:
            files_created = [f.path for f in verification_report.files_created if f.exists]
            files_modified = [f.path for f in verification_report.files_modified if f.exists]
            workspace_snapshot = verification_report.workspace_snapshot

            for cr in verification_report.command_results:
                if cr.test_summary:
                    has_tests = True
                    total_passed += cr.test_summary.get("passed", 0)
                    total_failed += cr.test_summary.get("failed", 0)
                    total_errors += cr.test_summary.get("errors", 0)
                    total_skipped += cr.test_summary.get("skipped", 0)
        else:
            # Fallback extraction from tool_results
            seen_files = set()
            for r in tool_results:
                tool_name = r.get("tool", "")
                success = r.get("success", False)
                arguments = r.get("arguments", {})

                # Check for write_file
                if tool_name == "write_file" and success:
                    from nakama_kun.orchestration.verification import _extract_paths_from_arguments

                    paths = _extract_paths_from_arguments(arguments)
                    for p in paths:
                        if p not in seen_files:
                            seen_files.add(p)
                            files_created.append(p)

                # Check for run_command test parsing fallback
                elif tool_name == "run_command":
                    cmd = arguments.get("cmd", "")
                    content = r.get("content", "")
                    json_content = content
                    if content.startswith("ERROR: "):
                        json_content = content[len("ERROR: "):]

                    # Try to parse as JSON first
                    stdout_val = json_content
                    try:
                        data = json.loads(json_content)
                        if isinstance(data, dict) and "stdout" in data:
                            stdout_val = data.get("stdout", "")
                    except Exception:
                        pass

                    from nakama_kun.orchestration.test_parser import parse_test_results

                    ts = parse_test_results(cmd, stdout_val)
                    if ts:
                        has_tests = True
                        total_passed += ts.get("passed", 0)
                        total_failed += ts.get("failed", 0)
                        total_errors += ts.get("errors", 0)
                        total_skipped += ts.get("skipped", 0)

        # Build structured metrics block
        metrics_lines = [
            "### STRUCTURED METRICS (TRUST AND CITE ONLY THESE METRICS)",
            f"- Total Tool Executions: {len(tool_results)} runs",
            f"- Files Created ({len(files_created)}): {', '.join(files_created) if files_created else '(none)'}",
            f"- Files Modified ({len(files_modified)}): {', '.join(files_modified) if files_modified else '(none)'}",
        ]
        if has_tests:
            metrics_lines.append(
                f"- Test Execution Summary:\n"
                f"  - Passed: {total_passed}\n"
                f"  - Failed: {total_failed}\n"
                f"  - Errors: {total_errors}\n"
                f"  - Skipped: {total_skipped}"
            )
        else:
            metrics_lines.append("- Test Execution Summary: No test suites were run.")

        if workspace_snapshot:
            metrics_lines.append(f"- Workspace Snapshot ({len(workspace_snapshot)} files):")
            for f in workspace_snapshot[:20]:
                metrics_lines.append(f"  - {f}")
            if len(workspace_snapshot) > 20:
                metrics_lines.append(f"  - ... and {len(workspace_snapshot) - 20} more files")

        metrics_block = "\n".join(metrics_lines)

        summary_prompt = (
            f"Synthesize a final report summarizing the agent's work.\n"
            f"User Goal: {goal}\n"
            f"Plan Proposed: {plan.goal_summary if plan else 'None'}\n\n"
            f"{metrics_block}\n\n"
            f"Create a beautiful markdown summary reporting what actions were completed. "
            f"You MUST only cite the files created/modified and test counts listed in the structured metrics block. "
            f"Do NOT invent, infer, or hallucinate other files, outcomes, or test metrics. If the metadata shows no tests ran, report that clearly."
        )

        messages = [
            Message(role="system", content="You are a helpful assistant reporting task results."),
            Message(role="user", content=summary_prompt),
        ]

        response = await chat_service.provider.generate(messages)
        content = response.content or ""

        return {"final_response": content, "status": "done"}

    return final_response_node
